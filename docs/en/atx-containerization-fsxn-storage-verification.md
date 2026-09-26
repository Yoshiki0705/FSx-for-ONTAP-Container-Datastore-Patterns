# Verifying FSx for ONTAP Data Store Configurations on Container Targets

**Purpose**: Determine from primary sources the feasibility of four ways to use Amazon FSx for NetApp ONTAP as a data area on container runtimes after AWS Transform containerization (ECS on EC2 / EKS on EC2 / ECS on Fargate / EKS on Fargate), and express the feasible ones as CloudFormation templates taken through static verification.

**Last Updated**: 2026-09-22
**Status**: Literature research + CloudFormation authoring + static verification (cfn-lint). No hands-on deployment (next stage)

Related: [Containerization (ECS / EKS) Derivation and FSx for ONTAP Integration](atx-containerization-fsxn-derivation.md). This memo follows that research to express "if it can be used, how to configure it" in CloudFormation.

---

## 1. Conclusion

All four configurations can use FSx for ONTAP as a data area. But **the access form differs by runtime**. The EC2 configurations use file mounts (NFS / iSCSI PV); the Fargate configurations use the S3 object API (S3 Access Points).

| # | Runtime | FSx for ONTAP access form | App change | CloudFormation | Tier |
|---|---|---|---|---|---|
| 1 | ECS on EC2 | NFS mounted on the EC2 host → bind mount | None (keeps file I/O) | [Authored](../../templates/containers-ecs-ec2-fsxn-nfs.yaml) | [Documented] |
| 2 | EKS on EC2 | Trident CSI PV (NFS `ontap-nas` / iSCSI `ontap-san`) | None (keeps file I/O) | [Authored](../../templates/containers-eks-ec2-fsxn-trident.yaml) | [Documented] |
| 3 | ECS on Fargate | S3 object API via S3 Access Points | Required (to S3 SDK) | [Authored](../../templates/containers-ecs-fargate-fsxn-s3ap.yaml) | [Documented] |
| 4 | EKS on Fargate | S3 object API via S3 Access Points | Required (to S3 SDK) | [Authored](../../templates/containers-eks-fargate-fsxn-s3ap.yaml) | [Documented] |

**Key point**: Fargate cannot use FSx for ONTAP through a volume mount, but it can through **object access** via S3 Access Points. If you want to keep file I/O as-is, choose the EC2 configurations (1 / 2); if you take serverless operation, choose the Fargate configurations (3 / 4) and move the app to the S3 SDK — a trade-off.

---

## 2. Evidence Tiers

| Tag | Meaning |
|---|---|
| **[Verified]** | Actually executed and confirmed in this repository |
| **[Documented]** | Stated in AWS / NetApp official documentation. Source URL included. Does not imply hands-on confirmation |
| **[Unverified]** | Not executed and not corroborated by public information. Investigation date and scope included |

The CloudFormation in this memo passes static verification (cfn-lint) as [Verified], but **it has not been verified to deploy and work** [Unverified].

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

- What CloudFormation can create: the EKS cluster, a managed node group, the Trident EKS add-on (`AWS::EKS::Addon`), an OIDC provider for IRSA, and the node security group. It adds NFS (2049) and iSCSI (3260) ingress to the existing FSx for ONTAP security group.
- What CloudFormation cannot create: the Kubernetes objects that produce a PV (TridentBackendConfig / StorageClass / PersistentVolumeClaim). These are applied with kubectl / Helm after the stack completes.
- The Trident EKS add-on name and version can change, so confirm before deploying with `aws eks describe-addon-versions --addon-name netapp_trident-operator`.

**Note when using iSCSI (stated symmetrically)**: when using `ontap-san` (block) alongside the Amazon EBS CSI driver, the node multipath configuration must blacklist EBS devices in `multipath.conf` so multipath does not claim them (source: stated in both the EKS User Guide above and the Trident documentation).

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

**What this verification does not say**: it has not been verified to deploy and work. The following are for hands-on verification (next stage) in particular.

| # | Item | Research / verification state (2026-09-22) |
|---|---|---|
| V1 | Deploying the four configurations and data connectivity | Not done. Only cfn-lint is [Verified] |
| V2 | Current Trident EKS add-on name and version | To confirm with describe-addon-versions [Unverified] |
| V3 | Whether EKS Pod Identity works on Fargate | This memo uses IRSA. Pod Identity on Fargate is unconfirmed [Unverified] |
| V4 | Mapping of the S3 access point UNIX user to ONTAP-side permissions | Permission design to confirm on real hardware [Unverified] |
| V5 | Effective throughput via the S3 access point | Docs state "depends on the file system's provisioned throughput". Not measured [Unverified] |

### 7.1 Deployment prerequisites (the stage before hands-on verification)

Before confirming V1–V5 on real infrastructure, these are the prerequisites, order, pitfalls, and cleanup, framed to prevent rework. Real deployment incurs charges and changes a shared account, so obtain per-action approval when starting it.

**Prerequisite: FSx for ONTAP is outside this repository's templates** [Verified]. None of the five templates create `AWS::FSx::FileSystem` / `StorageVirtualMachine` / `Volume`; they reference an existing FSx for ONTAP. As stage 0 of deployment, provision the file system + SVM + volume first, and record the SVM NFS endpoint, the volume junction path, and the file system security group ID (passed to config 1's `FsxnSvmNfsEndpoint` / `FsxnVolumeJunctionPath` / `FsxnSecurityGroupId`).

**Confirmed design decisions (do not undo on real infra)**:

- NFS explicitly uses `nfsvers=4.1`, which completes over the single port 2049 [Verified]. Ingress on 2049 only is correct. 111 / 635 / 4045-4049 are for NFSv3 and are not needed here.
- The S3 Access Point policy circular reference is already avoided by setting the Principal to the account root and scoping on the role's identity policy (5.2).

**Items to confirm before starting (mapped to the V numbers)**:

| Preparation | Related unverified item | How to confirm |
|---|---|---|
| Current Trident EKS add-on name / version | V2 | `aws eks describe-addon-versions --addon-name netapp_trident-operator`. Docs are now on the Trident 25.10 line, ahead of this memo's 25.02 reference [Documented] |
| S3 Access Point dual-layer authorization (IAM + file-system-level UNIX / Windows user) | V4 | Design the mapping between the access point's UNIX user and the ONTAP file permissions on real infra [Documented] |
| Availability in the target region | V1 in general | Second-generation FSx for ONTAP expanded to four regions + GovCloud in 2026-04. S3 Access Points support Tokyo (ap-northeast-1) [Documented]. Confirm availability in the region you use |
| IRSA trust condition (EKS Fargate) | V3 | Add `sub` / `aud` to the trust policy manually after cluster creation (5.2). Do not leave it unset on a shared account |

**Recommended deployment order**: start with the smallest, config 1 (ECS on EC2 + NFS — CloudFormation-complete, no Trident, no S3 Access Points). Once the data path is confirmed (read/write to `/data` from a task), delete it, then proceed step by step to config 2 (apply Trident's Kubernetes objects via kubectl / Helm) and configs 3 / 4 (S3 Access Points, with the manual IRSA step).

**Pitfalls (the kind that force rework on real infra)**:

- The mount is an instance boot-time step, not something a task creates. If a task starts before the mount is present, the bind-mount target is empty (already noted in 3.2). Treat the mount as a precondition of startup.
- When using `ontap-san` (iSCSI) alongside the Amazon EBS CSI driver, blacklist EBS devices in `multipath.conf` or the node multipath will claim EBS (already noted in 4.2).
- Trident's StorageClass / PVC / TridentBackendConfig cannot be created by CloudFormation; apply them with kubectl / Helm after the stack completes (already noted in 4.2).

**Cleanup (a verification environment is exactly where you must delete)**: the main resources that keep charging are the FSx for ONTAP file system (hourly for SSD capacity + provisioned throughput), the EKS cluster, EC2 nodes / container instances, and NAT / VPC endpoints. After verification, delete the stack, and do not forget the FSx for ONTAP created outside the templates. A verification resource you cannot delete becomes a long-running charge and blocks operations on resources beside it.

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
