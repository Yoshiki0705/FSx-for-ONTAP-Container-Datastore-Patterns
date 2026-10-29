# Verifying FSx for ONTAP Data Store Configurations on Container Targets

**Purpose**: Determine from primary sources the feasibility of four ways to use Amazon FSx for NetApp ONTAP as a data area on container runtimes after AWS Transform containerization (ECS on EC2 / EKS on EC2 / ECS on Fargate / EKS on Fargate), and express the feasible ones as CloudFormation templates taken through static verification.

**Last Updated**: 2026-10-29
**Status**: Literature research + CloudFormation authoring + static verification (cfn-lint) + a small-scale hands-on deployment of config 2 (4.3). No hands-on deployment of configs 1, 3, and 4 (next stage)

Related: [Containerization (ECS / EKS) Derivation and FSx for ONTAP Integration](atx-containerization-fsxn-derivation.md). This memo follows that research to express "if it can be used, how to configure it" in CloudFormation.

---

## 1. Conclusion

All four configurations can use FSx for ONTAP as a data area. But **the access form differs by runtime**. The EC2 configurations use file mounts (NFS / iSCSI PV); the Fargate configurations use the S3 object API (S3 Access Points).

| # | Runtime | FSx for ONTAP access form | App change | CloudFormation | Tier |
|---|---|---|---|---|---|
| 1 | ECS on EC2 | NFS mounted on the EC2 host → bind mount | None (keeps file I/O) | [Authored](../../templates/containers-ecs-ec2-fsxn-nfs.yaml) | [Documented] |
| 2 | EKS on EC2 | Trident CSI PV (NFS `ontap-nas` / iSCSI `ontap-san`) | None (keeps file I/O) | [Authored](../../templates/containers-eks-ec2-fsxn-trident.yaml) | [Documented] · [Verified] (4.3) |
| 3 | ECS on Fargate | S3 object API via S3 Access Points | Required (to S3 SDK) | [Authored](../../templates/containers-ecs-fargate-fsxn-s3ap.yaml) | [Documented] |
| 4 | EKS on Fargate | S3 object API via S3 Access Points | Required (to S3 SDK) | [Authored](../../templates/containers-eks-fargate-fsxn-s3ap.yaml) | [Documented] |

**Key point**: Fargate cannot use FSx for ONTAP through a volume mount, but it can through **object access** via S3 Access Points. If you want to keep file I/O as-is, choose the EC2 configurations (1 / 2); if you take serverless operation, choose the Fargate configurations (3 / 4) and move the app to the S3 SDK. That is the trade-off.

---

## 2. Evidence Tiers

| Tag | Meaning |
|---|---|
| **[Verified]** | Actually executed and confirmed in this repository |
| **[Documented]** | Stated in AWS / NetApp official documentation. Source URL included. Does not imply hands-on confirmation |
| **[Unverified]** | Not executed and not corroborated by public information. Investigation date and scope included |

The CloudFormation in this memo passes static verification (cfn-lint) as [Verified]. Only config 2 was deployed and checked, at small scale (4.3). **Configs 1, 3, and 4 have not been verified to deploy and work** [Unverified].

---

## 3. Config 1: ECS on EC2 + NFS mount

### 3.1 Feasibility [Documented]

The procedure for using FSx for ONTAP from ECS is documented assuming the EC2 launch type (source: [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html)). An EC2 Linux instance mounts the SVM volume over NFS, and the task definition bind-mounts it into the container via `volumes` (`host.sourcePath`) and `mountPoints`. Windows uses SMB global mapping.

### 3.2 CloudFormation design

- The network is selectable: `CreateNetwork=true` creates a minimal VPC / subnets, `false` references existing ones.
- The container instance launch template's `user-data` installs the NFS client and mounts the SVM endpoint and junction path at `/mnt/fsxontap`, registering it in `fstab`.
- The task definition bind-mounts `host.sourcePath: /mnt/fsxontap` to `/data`.
- An NFS (2049) ingress from the ECS instances is added to the existing FSx for ONTAP security group.

**Note**: the mount is an instance bootstrap action, not something the task creates. If a task starts before the mount, the bind-mount target is empty. Treat the mount as a launch prerequisite.

---

## 4. Config 2: EKS on EC2 + Trident CSI

### 4.1 Feasibility [Documented]

The AWS EKS User Guide points to NetApp Trident as the means of FSx for ONTAP integration (source: [Use high-performance app storage with FSx for NetApp ONTAP](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html)). Trident can provision both NFS (`ontap-nas`) and iSCSI (`ontap-san`) PVs (source: [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html)).

Trident runs a controller pod plus a node pod (DaemonSet) on each worker node, so it **requires EC2 worker nodes** and cannot run on Fargate (source: [Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html)). That is why this configuration creates a managed node group.

### 4.2 CloudFormation design, and what CloudFormation cannot create

- What CloudFormation can create: the EKS cluster, a managed node group, the Trident EKS add-on (`AWS::EKS::Addon`), an OIDC provider for IRSA, and, when `PrepareNodesForIscsi=true`, the node preparation for iSCSI (a launch template). It adds management (443), NFS (2049), and iSCSI (3260) ingress to the existing FSx for ONTAP security group, with the EKS cluster security group as the source. That cluster security group is the one attached to the managed nodes; an additional security group passed in `ResourcesVpcConfig` applies to the control-plane network interfaces and is not attached to the nodes [Verified: 2026-10-29, ap-northeast-1, 2 nodes, 1 observation].
- What CloudFormation cannot create: the Kubernetes objects that produce a PV (TridentBackendConfig / StorageClass / PersistentVolumeClaim). These are applied with kubectl / Helm after the stack completes.
- The Trident EKS add-on name and version can change, so confirm before deploying with `aws eks describe-addon-versions --addon-name netapp_trident-operator`.
- `KubernetesVersion` has no default. A default goes stale without any change to the template when a version moves from standard to extended support (on 2026-10-29 in ap-northeast-1, 1.31 was in extended support [Verified]). Check the versions in standard support with `aws eks describe-cluster-versions` and pass one explicitly.

**Note when using iSCSI (stated symmetrically)**: when using `ontap-san` (block) alongside the Amazon EBS CSI driver, the node multipath configuration must blacklist EBS devices in `multipath.conf` so multipath does not claim them (source: stated in both the EKS User Guide above and the Trident documentation).

The Amazon Linux 2023 EKS AMI does not include the iSCSI tools (`iscsi-initiator-utils`, `device-mapper-multipath`, `lsscsi`); `nfs-utils` is included [Verified: 2026-10-29, ap-northeast-1, 2 nodes, 1 observation]. The template installs them through launch template user data and writes `multipath.conf`. Running the same commands through SSM Run Command made a SAN PV work [Verified]. Deploying the changed template, the user data ran at the nodes' first boot: the packages were installed, `iscsid` and `multipathd` were active, `multipath.conf` had the expected content, and the Trident node pods detected iSCSI on both nodes without a restart [Verified: 2026-10-29, ap-northeast-1, 2 nodes, 1 observation]. A separate deployment on the same day reached the same state with no manual step, and SAN and NAS PVs kept their data (4.3). The `iscsid` start and the kubelet start fell in the same second, so no ordering is guaranteed. If a node pod started before the tools were installed, restart the `trident-node-linux` DaemonSet.

### 4.3 Hands-on results for config 2

**Scope**: two runs on 2026-10-29, ap-northeast-1, an existing Single-AZ FSx for ONTAP file system, one observation each. The first run used the revision before the launch template of 4.2 was added, the second the revision after it. This is a small-scale check. It does not cover sustained operation, performance, Multi-AZ failover, or consistency when several pods write the same file at once.

| Item | Detail |
|---|---|
| Kubernetes | v1.35 (a version in standard support) |
| Nodes | 2 × m5.large (different AZs), Amazon Linux 2023 |
| Trident add-on | `netapp_trident-operator` v26.6.2-eksbuild.1 (the default) |
| ONTAP | NetApp Release 9.18.1P6 (retrieved in the second run; not retrieved in the first) |
| SVM | A dedicated SVM created for the check, with its own `vsadmin` |
| Backend authentication | A Kubernetes Secret. Referencing Secrets Manager (`awsarn`) needs extra IRSA setup and was not tried |
| StorageClass and PVC | `ontap-san` and `ontap-nas`, reclaim policy `Delete`, one 1 GiB PVC each |

| Type | Check | Result [Verified] |
|---|---|---|
| iSCSI / RWO | PVC provisioning | `Bound` in about 10 seconds (`ReadWriteOnce`) |
| iSCSI / RWO | After writing a marker, after a pod restart (same node), and after cordoning the node and deleting the pod (other node, other AZ) | The marker matched all three times. The new pod started only after the old pod had finished deleting. Both nodes mounted the same multipath device (ext4) |
| NFS / RWX | PVC provisioning | `Bound` in about 10 seconds (`ReadWriteMany`) |
| NFS / RWX | Pod B on another node reads what pod A wrote | Matched (NFS v4.2) |
| NFS / RWX | After restarting the Deployment so every pod was new | Matched. An append made after the restart was readable from another pod |

**Scope of the observation**: the results in the table above were the same in both runs. In the first run the node preparation was applied by hand with SSM Run Command. In the second run there was no manual step: the Trident node pods restarted 0 times and both nodes could use iSCSI (clean in `tridentctl get node`).

| Type | Check (second run) | Result [Verified] |
|---|---|---|
| Importing an existing volume | A pod without a PVC writes a file to a volume created with the FSx API. A PVC with the annotations `trident.netapp.io/importOriginalName` and `trident.netapp.io/importBackendUUID` imports it | `Bound` in about 10 seconds. A pod read the file written before the import. On ONTAP the volume was renamed to `trident_pvc_…`; its UUID and junction path did not change |
| Import and reclaim policy | Import with a StorageClass whose reclaim policy is `Retain`, then delete the PVC and the PV object | The volume stayed on ONTAP. Trident kept its record of the volume, and deleting the TridentBackendConfig stayed at `Backend is in a deleting state`. Removing the record with `tridentctl delete volume <PV name>` let the deletion finish |
| Wrong credentials | Create a TridentBackendConfig that references a Secret with a wrong password | `Failed`, `401 (Unauthorized): incorrect or missing credentials`. The PVC stayed `Pending` with the event `no available backends for storage class` |
| Management LIF unreachable | Give an unused IP as the management LIF | `Failed`, `connect: no route to host`. The PVC stayed `Pending` with the same event |
| Changing the Secret of a working backend | Replace the correct password with a wrong one | The backend stayed `Success` and kept using the old credentials until it was reloaded. A reload (a change to the TridentBackendConfig spec) turned it `Failed`. Reads and writes of existing pods never stopped; only provisioning of new PVCs stopped |

**SVM user lockout**: after the two failure checks above, authentication returned `401` (ONTAP error code 6691623) even with the correct password restored. `vsadmin` was locked on ONTAP. The SAN backend, which uses the same `vsadmin`, also turned `Failed`. The lock did not clear by itself. After unlocking it as the file system administrator (`fsxadmin`), both backends returned to `Success` and the waiting PVCs became `Bound`. The likely cause is repeated authentication with a wrong password, from the wrong-credentials check and the reloads. The lockout threshold and the moment of locking were not read. To check failure shapes, use a separate SVM user or run them after the other checks.

**Teardown observation**: with reclaim policy `Delete`, deleting the PVC removed the LUN and the volume from ONTAP (checked with the ONTAP REST API). Ten seconds after deleting the SAN PVC, the SAN volume was still present, so the deletion is asynchronous. The file system's backup count was the same before and after teardown, and no final backup was created. This file system did not return a retention period for automatic backups, so environments with automatic backups enabled are unchecked.

**A note on the check Deployment**: combining a required anti-affinity that puts pods on different nodes with the default rolling update (`maxSurge` 25%) stalled the update when the number of nodes equalled the number of pods, because the extra pod had nowhere to go. Setting `maxSurge: 0` and `maxUnavailable: 1` resolved it.

The difference between the FSx API and the ONTAP volume list is described in 7.1. In the second run the Trident volumes did not appear in the FSx API when the SVM was deleted, about 55 minutes after creation, and the SVM deletion was accepted on the first request. Appearance and disappearance times were not measured in the second run.

---

## 5. Config 3 / 4: Fargate + S3 Access Points

### 5.1 Feasibility [Documented]

FSx for ONTAP S3 Access Points let you read/write volume data through the S3 object API (GetObject / PutObject / ListObjectsV2, etc.). The data stays on FSx for ONTAP and can be used alongside NFS / SMB (source: [Accessing your data via Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/accessing-data-via-s3-access-points.html)).

**Why it works on Fargate**: this is not a volume mount but an app calling S3 with the SDK. Fargate's DaemonSet / privileged / CSI constraints (which blocked Config 2) do not apply. Official documentation lists in-VPC compute including "Amazon ECS tasks within the VPC" as a Gateway-endpoint use case (source: [Configuring network access for Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)). Fargate tasks / pods have an ENI in the VPC and are therefore in-VPC compute.

Supported regions include Tokyo (ap-northeast-1) [Documented].

### 5.2 CloudFormation design

- The FSx for ONTAP S3 access point can be created with the CloudFormation resource `AWS::FSx::S3AccessPointAttachment` (not CLI-only). Set the network origin to VPC and specify the UNIX user that authorizes file access.
- In-VPC S3 traffic goes through the free S3 Gateway VPC endpoint, which populates `aws:SourceVpc` so a VPC-origin access point accepts the request.
- Authentication is a container-side IAM role. Config 3 (ECS Fargate) uses the task role; Config 4 (EKS Fargate) uses IRSA (OIDC provider + IAM role + service account annotation).

**Avoiding the access point policy cycle**: if the task / IRSA role references the access point ARN and the access point policy references that role ARN, they cycle. In the same account, either the identity policy or the access point policy granting access is sufficient, so the access point policy's Principal is set to the account root and the role's identity policy scopes to the access point. VPC origin denies any request from outside the VPC.

**IRSA trust condition (Config 4)**: the condition key `<oidc-issuer>:sub` depends on an issuer host known only after the cluster is created, and CloudFormation cannot build a condition *key* from an intrinsic function. So the template grants only the Federated principal, and the `sub` / `aud` scoping is added to the trust policy after deployment. Do not leave it unscoped in a shared account.

### 5.3 Object API constraints [Documented]

Because access is via the S3 SDK, the app must be written for object access. It cannot be used as a mounted file system. Main constraints (source: [Access point compatibility](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)):

- Maximum object size for uploads is 50 GiB.
- Storage class is FSX_ONTAP only; server-side encryption is SSE-FSX only.
- Not supported: versioning, Object Lock, lifecycle, conditional writes, Requester Pays, static website hosting, ACLs other than `bucket-owner-full-control`.
- CopyObject / UploadPartCopy are same-access-point and same-Region only.

---

## 6. Four Configurations × Storage Pattern Matrix

| Aspect | Config 1 ECS/EC2 | Config 2 EKS/EC2 | Config 3 ECS/Fargate | Config 4 EKS/Fargate |
|---|---|---|---|---|
| FSx for ONTAP access form | NFS host mount → bind mount | Trident PV (NFS / iSCSI) | S3 Access Points (object) | S3 Access Points (object) |
| Access granularity | File (POSIX) | File (NFS) / block (iSCSI) | Object | Object |
| Sharing (multiple tasks / pods) | Yes (NFS) | NFS can be RWX / iSCSI mostly RWO | Yes (object) | Yes (object) |
| App change | None | None | Required (S3 SDK) | Required (S3 SDK) |
| Authentication | Via host (no IAM) | Secrets Manager / cert (Trident) | Task role (IAM) | IRSA (IAM) |
| Main use cases | Migration assuming existing files | Stateful / DB / shared files | Analytics / AI / object-first | Same |
| Out of CloudFormation scope | None (all CFn) | PV objects (kubectl) | None (all CFn) | Service account annotation / trust sub |

---

## 7. Static Verification Results [Verified / 2026-09-22]

Confirmed that `make cfn-lint` (cfn-lint, `templates/*.yaml`) passes with exit 0, covering the four templates plus the two existing ones. A `params/*.example.json` with dummy values was prepared for each template, and the keys were confirmed to match the template parameters (the new-network CIDR parameters in Config 1 have defaults and are omitted when referencing existing resources).

**What this verification does not say**: configs other than 2 have not been verified to deploy and work. The config 2 results are in 4.3. The following are the items to confirm on real infrastructure; V1 and V2 are already confirmed for config 2.

| # | Item | Research / verification state (2026-09-22) |
|---|---|---|
| V1 | Deploying the four configurations and data connectivity | Config 2 was checked on 2026-10-29 (4.3) [Verified]. Configs 1, 3, and 4 are not done; only cfn-lint is [Verified] |
| V2 | Current Trident EKS add-on name and version | On 2026-10-29 in ap-northeast-1, `netapp_trident-operator` existed, the default was v26.6.2-eksbuild.1, and the highest supported Kubernetes version was 1.36 [Verified]. Names and versions change, so reconfirm before deploying |
| V3 | Whether EKS Pod Identity works on Fargate | This memo uses IRSA. Pod Identity on Fargate is unconfirmed [Unverified] |
| V4 | Mapping of the S3 access point UNIX user to ONTAP-side permissions | Permission design to confirm on real hardware [Unverified] |
| V5 | Effective throughput via the S3 access point | Docs state "depends on the file system's provisioned throughput". Not measured [Unverified] |

### 7.1 Deployment prerequisites (the stage before hands-on verification)

Before confirming V1–V5 on real infrastructure, these are the prerequisites, order, pitfalls, and cleanup, framed to prevent rework. Real deployment incurs charges and changes a shared account, so obtain per-action approval when starting it.

**Prerequisite: FSx for ONTAP is outside this repository's templates** [Verified]. None of the five templates create `AWS::FSx::FileSystem` / `StorageVirtualMachine` / `Volume`; they reference an existing FSx for ONTAP. As stage 0 of deployment, provision the file system + SVM + volume first, and record the SVM NFS endpoint, the volume junction path, and the file system security group ID (passed to config 1's `FsxnSvmNfsEndpoint` / `FsxnVolumeJunctionPath` / `FsxnSecurityGroupId`).

**Confirmed design decisions (do not undo on real infra)**:

- Config 1's template explicitly sets `nfsvers=4.1` for the NFS mount [Verified]. That NFSv4.1 completes over the single port 2049, and that 111 / 635 / 4045-4049 are for NFSv3 and are not needed for v4.1-only, is stated in AWS documentation and is not verified as ingress connectivity in this repository [Documented] (source: [Use NFS to mount FSx for ONTAP volume on Linux instance](https://repost.aws/knowledge-center/ec2-mount-fsx-ontap-nfs)). So designing the template ingress as 2049-only is consistent on the v4.1 assumption.
- The S3 Access Point policy circular reference is already avoided by setting the Principal to the account root and scoping on the role's identity policy (5.2).

**Items to confirm before starting (mapped to the V numbers)**:

| Preparation | Related unverified item | How to confirm |
|---|---|---|
| Current Trident EKS add-on name / version | V2 | `aws eks describe-addon-versions --addon-name netapp_trident-operator`. On 2026-10-29 in ap-northeast-1 the default was v26.6.2-eksbuild.1, ahead of this memo's 25.02 reference [Verified] |
| S3 Access Point dual-layer authorization (IAM + file-system-level UNIX / Windows user) | V4 | Design the mapping between the access point's UNIX user and the ONTAP file permissions on real infra [Documented] |
| Availability in the target region | V1 in general | Second-generation FSx for ONTAP expanded to four regions + GovCloud in 2026-04. S3 Access Points support Tokyo (ap-northeast-1) [Documented]. Confirm availability in the region you use |
| IRSA trust condition (EKS Fargate) | V3 | Add `sub` / `aud` to the trust policy manually after cluster creation (5.2). Do not leave it unset on a shared account |

**Recommended deployment order**: start with the smallest, config 1 (ECS on EC2 + NFS, which is CloudFormation-complete, with no Trident and no S3 Access Points). Once the data path is confirmed (read/write to `/data` from a task), delete it, then proceed step by step to config 2 (apply Trident's Kubernetes objects via kubectl / Helm) and configs 3 / 4 (S3 Access Points, with the manual IRSA step).

**Pitfalls (the kind that force rework on real infra)**:

- The mount is an instance boot-time step, not something a task creates. If a task starts before the mount is present, the bind-mount target is empty (already noted in 3.2). Treat the mount as a precondition of startup.
- When using `ontap-san` (iSCSI) alongside the Amazon EBS CSI driver, blacklist EBS devices in `multipath.conf` or the node multipath will claim EBS (already noted in 4.2).
- Trident's StorageClass / PVC / TridentBackendConfig cannot be created by CloudFormation; apply them with kubectl / Helm after the stack completes (already noted in 4.2).
- The FSx API reflects the volumes that Trident creates on the ONTAP side with a delay. If you check for leftovers after teardown with the FSx API alone, you read "absent" right after creation and "still there" right after deletion. Check with the ONTAP REST API (reached from inside the VPC through the management LIF). The FSx API did not list the volumes at 23 seconds and at 11 minutes after creation, and listed them at 26 minutes. After the volumes were deleted on ONTAP, the FSx API still listed them at 41 minutes and no longer did at 44 minutes [Verified: 2026-10-29, ap-northeast-1, 1 observation]. While the FSx API showed a non-root volume, deleting the SVM was rejected with `BadRequest`.

**Cleanup (a verification environment is exactly where you must delete)**: the main resources that keep charging are the FSx for ONTAP file system (hourly for SSD capacity + provisioned throughput), the EKS cluster, EC2 nodes / container instances, and NAT / VPC endpoints. After verification, delete the stack, and do not forget the FSx for ONTAP created outside the templates. A verification resource you cannot delete becomes a long-running charge and blocks operations on resources beside it.

**Teardown order with Trident**: before deleting the stack, delete the application Deployment, the PVCs (SAN and NAS separately), the StorageClasses, and the TridentBackendConfigs in that order. If a PV has reclaim policy `Retain`, deleting the PV object leaves Trident's record, so remove it with `tridentctl delete volume` before deleting the TridentBackendConfig (4.3). Then confirm with the ONTAP REST API that the LUN and the volumes are gone from ONTAP. Then delete the stack. If you created a dedicated SVM for the check, delete it once the FSx API no longer shows a non-root volume.

---

## 8. The Split Decision

If hands-on verification confirms feasibility, this set of artifacts (CloudFormation for the four configurations plus app-side change examples) has room to be split into a separate repository / Kiro project from the EC2 rehost verification (existing), because the target is source code and containers and the verification stack (ECS / EKS / Trident / S3 Access Points) is a different lineage from VMware migration. Whether to split is decided after hands-on verification.

---

## Reference Links

- [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html)
- [Use high-performance app storage with FSx for NetApp ONTAP (EKS User Guide)](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html)
- [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html)
- [Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html)
- [Accessing your data via Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/accessing-data-via-s3-access-points.html)
- [Configuring network access for Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)
- [Access point compatibility](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)
- [AWS::FSx::S3AccessPointAttachment (CloudFormation)](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-fsx-s3accesspointattachment.html) <!-- allow:naming — literal CloudFormation resource type name -->
- [Containerization Derivation and FSx for ONTAP Integration (this repository)](atx-containerization-fsxn-derivation.md)
