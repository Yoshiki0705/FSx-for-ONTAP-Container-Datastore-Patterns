# Verifying FSx for ONTAP Data Store Configurations on Container Targets

**Purpose**: Determine from primary sources the feasibility of four ways to use Amazon FSx for NetApp ONTAP as a data area on container runtimes after AWS Transform containerization (ECS on EC2 / EKS on EC2 / ECS on Fargate / EKS on Fargate), and express the feasible ones as CloudFormation templates taken through static verification.

**Last Updated**: 2026-10-29
**Status**: Literature research + CloudFormation authoring + static verification (cfn-lint) + small-scale hands-on deployments of configs 1 and 2 (3.3 and 4.3). No hands-on deployment of configs 3 and 4 (next stage)

Related: [Containerization (ECS / EKS) Derivation and FSx for ONTAP Integration](atx-containerization-fsxn-derivation.md). This memo follows that research to express "if it can be used, how to configure it" in CloudFormation.

---

## 1. Conclusion

All four configurations can use FSx for ONTAP as a data area. But **the access form differs by runtime**. The EC2 configurations use file mounts (NFS / iSCSI PV); the Fargate configurations use the S3 object API (S3 Access Points).

| # | Runtime | FSx for ONTAP access form | App change | CloudFormation | Tier |
|---|---|---|---|---|---|
| 1 | ECS on EC2 | NFS mounted on the EC2 host → bind mount | None (keeps file I/O) | [Authored](../../templates/containers-ecs-ec2-fsxn-nfs.yaml) | [Documented]・[Tested] (3.3) |
| 2 | EKS on EC2 | Trident CSI PV (NFS `ontap-nas` / iSCSI `ontap-san`) | None (keeps file I/O) | [Authored](../../templates/containers-eks-ec2-fsxn-trident.yaml) | [Documented] · [Tested] (4.3) |
| 3 | ECS on Fargate | S3 object API via S3 Access Points | Required (to S3 SDK) | [Authored](../../templates/containers-ecs-fargate-fsxn-s3ap.yaml) | [Documented]・[Tested] (5.4) |
| 4 | EKS on Fargate | S3 object API via S3 Access Points | Required (to S3 SDK) | [Authored](../../templates/containers-eks-fargate-fsxn-s3ap.yaml) | [Documented]・[Tested] (5.4) |

**Key point**: Fargate cannot use FSx for ONTAP through a volume mount, but it can through **object access** via S3 Access Points. If you want to keep file I/O as-is, choose the EC2 configurations (1 / 2); if you take serverless operation, choose the Fargate configurations (3 / 4) and move the app to the S3 SDK. That is the trade-off.

---

## 2. Evidence Tiers

| Tag | Meaning |
|---|---|
| **[Tested]** | Executed and confirmed on real infrastructure in this repository |
| **[Documented]** | Stated in AWS / NetApp docs, not verified in a real environment. Source URL included |
| **[Not measured]** | Not executed, or out of scope here. Investigation date and scope included |

The CloudFormation in this memo passes static verification (cfn-lint) as [Tested]. Configs 1 (3.3), 2 (4.3), and 3 and 4 (5.4) were deployed and checked at small scale.

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

### 3.3 Hands-on results for config 1

**Scope**: 2026-11-10, ap-northeast-1, a disposable SVM and volume (UNIX style, 1 GiB, junction path `/ecsvol`) created on the existing Single-AZ FSx for ONTAP, one observation per item, stack lifetime about 25 minutes. The template was the origin/main version at 09c079b, unmodified. This is a small-scale check; it does not cover performance, Multi-AZ failover, consistency when several tasks write the same file at once, or Windows (SMB, config 1b).

| Item | Result [Tested] |
|---|---|
| Creating the stack | The ECS service never reached a steady state, so the stack did not reach `CREATE_COMPLETE` on its own. The cause was not the mount: the placeholder image (`amazonlinux`) exits at once (exit 0) without arguments, and the service kept restarting the task. Setting the service's desired count to 0 let the stack finish. I added a `ContainerCommand` parameter to the template (default `sleep infinity`; an empty string uses your own image's CMD). That change passed cfn-lint only and was not deployed |
| Host mount (two instances) | `/mnt/fsxontap` was mounted over NFS v4.1 on both. The ingress was 2049 only (111 and the others were not opened) |
| Sharing between tasks on different instances | A marker written to `/data` by a task on instance 1 was read, identical, by a task on instance 2 |
| Replacing the task | After stopping the writing task, a new task read the same marker |
| Replacing the instance | After terminating instance 1, a task placed on the instance that Auto Scaling launched found the mount in place from boot and read the same marker |

I wrote and read the marker with `start-task` command overrides (`sh -c`) on the unchanged task definition and read the output in CloudWatch Logs. I did not use ECS Exec (the template has no task role). After teardown, the SVMs, volumes, backups, the FSx security group ingress, and the network interface count (72) matched the baseline.

**Limits of the observation**: the NFS export policy was left at the default of a new FSx for ONTAP SVM. A design that restricts it to client CIDRs was not tested.

---

## 4. Config 2: EKS on EC2 + Trident CSI

### 4.1 Feasibility [Documented]

The AWS EKS User Guide points to NetApp Trident as the means of FSx for ONTAP integration (source: [Use high-performance app storage with FSx for NetApp ONTAP](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html)). Trident can provision both NFS (`ontap-nas`) and iSCSI (`ontap-san`) PVs (source: [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html)).

Trident runs a controller pod plus a node pod (DaemonSet) on each worker node, so it **requires EC2 worker nodes** and cannot run on Fargate (source: [Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html)). That is why this configuration creates a managed node group.

### 4.2 CloudFormation design, and what CloudFormation cannot create

- What CloudFormation can create: the EKS cluster, a managed node group, the Trident EKS add-on (`AWS::EKS::Addon`), an OIDC provider for IRSA, and, when `PrepareNodesForIscsi=true`, the node preparation for iSCSI (a launch template). It adds management (443), NFS (2049), and iSCSI (3260) ingress to the existing FSx for ONTAP security group, with the EKS cluster security group as the source. That cluster security group is the one attached to the managed nodes; an additional security group passed in `ResourcesVpcConfig` applies to the control-plane network interfaces and is not attached to the nodes [Tested: 2026-10-29, ap-northeast-1, 2 nodes, 1 observation].
- What CloudFormation cannot create: the Kubernetes objects that produce a PV (TridentBackendConfig / StorageClass / PersistentVolumeClaim). These are applied with kubectl / Helm after the stack completes.
- The Trident EKS add-on name and version can change, so confirm before deploying with `aws eks describe-addon-versions --addon-name netapp_trident-operator`.
- `KubernetesVersion` has no default. A default goes stale without any change to the template when a version moves from standard to extended support (on 2026-10-29 in ap-northeast-1, 1.31 was in extended support [Tested]). Check the versions in standard support with `aws eks describe-cluster-versions` and pass one explicitly.

**Note when using iSCSI (stated symmetrically)**: when using `ontap-san` (block) alongside the Amazon EBS CSI driver, the node multipath configuration must blacklist EBS devices in `multipath.conf` so multipath does not claim them (source: stated in both the EKS User Guide above and the Trident documentation).

The Amazon Linux 2023 EKS AMI does not include the iSCSI tools (`iscsi-initiator-utils`, `device-mapper-multipath`, `lsscsi`); `nfs-utils` is included [Tested: 2026-10-29, ap-northeast-1, 2 nodes, 1 observation]. The template installs them through launch template user data and writes `multipath.conf`. Running the same commands through SSM Run Command made a SAN PV work [Tested]. Deploying the changed template, the user data ran at the nodes' first boot: the packages were installed, `iscsid` and `multipathd` were active, `multipath.conf` had the expected content, and the Trident node pods detected iSCSI on both nodes without a restart [Tested: 2026-10-29, ap-northeast-1, 2 nodes, 1 observation]. A separate deployment on the same day reached the same state with no manual step, and SAN and NAS PVs kept their data (4.3). The `iscsid` start and the kubelet start fell in the same second, so no ordering is guaranteed. If a node pod started before the tools were installed, restart the `trident-node-linux` DaemonSet.

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

| Type | Check | Result [Tested] |
|---|---|---|
| iSCSI / RWO | PVC provisioning | `Bound` in about 10 seconds (`ReadWriteOnce`) |
| iSCSI / RWO | After writing a marker, after a pod restart (same node), and after cordoning the node and deleting the pod (other node, other AZ) | The marker matched all three times. The new pod started only after the old pod had finished deleting. Both nodes mounted the same multipath device (ext4) |
| NFS / RWX | PVC provisioning | `Bound` in about 10 seconds (`ReadWriteMany`) |
| NFS / RWX | Pod B on another node reads what pod A wrote | Matched (NFS v4.2) |
| NFS / RWX | After restarting the Deployment so every pod was new | Matched. An append made after the restart was readable from another pod |

**Scope of the observation**: the results in the table above were the same in both runs. In the first run the node preparation was applied by hand with SSM Run Command. In the second run there was no manual step: the Trident node pods restarted 0 times and both nodes could use iSCSI (clean in `tridentctl get node`).

| Type | Check (second run) | Result [Tested] |
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

The use cases of access points, how to choose the origin, and the check status of integrations with AWS services and SaaS products are in [Use cases and integrations for S3 Access Points](s3-access-points-usecase-map.md). This memo is where the measurements live.

### 5.2 CloudFormation design

- The FSx for ONTAP S3 access point can be created with the CloudFormation resource `AWS::FSx::S3AccessPointAttachment` (not CLI-only). Set the network origin to VPC and specify the UNIX user that authorizes file access.
- In-VPC S3 traffic goes through the free S3 Gateway VPC endpoint, which populates `aws:SourceVpc` so a VPC-origin access point accepts the request.
- If the VPC already has an S3 Gateway endpoint covering the route table of the task / Pod subnets, reuse it with `CreateS3GatewayEndpoint=false`. A route table can hold only one endpoint route to the same service, so creating a second one fails [Documented] ([Gateway endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/vpce-gateway.html)). Configs 3 and 4 deployed through the reuse path (`CreateS3GatewayEndpoint=false`) and the S3 calls succeeded (5.4) [Tested]. That creating a second one fails has not been observed [Not measured].
- For Config 4, so that CoreDNS runs on a Fargate-only cluster, the template creates a Fargate profile that matches `kube-system` + `k8s-app=kube-dns` and a coredns add-on with `computeType=Fargate`. CoreDNS is scheduled onto EC2 by default, so without this the Pods cannot resolve names and the S3 SDK fails [Documented] ([Get started with AWS Fargate](https://docs.aws.amazon.com/eks/latest/userguide/fargate-getting-started.html)). `computeType` exists as a configuration key of the coredns add-on [Tested: 2026-11-10, `describe-addon-configuration`]. When deployed, the CoreDNS Pods reached Running on Fargate (5.4) [Tested]. <!-- spoke-checked: computetype --> <!-- spoke-checked: pods -->
- The `FileSystemIdentity` (a UNIX user) must be a user the SVM can resolve. The hub's measurements record that an access point whose user was created in the SVM's local (`files`) database became AVAILABLE and could read and write, and that pinning a non-root `nobody` made writes fail on a root-owned, 755 volume [Documented] ([Hub: layers of access point authorization (Japanese)](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md), measured 2026-08-17 / 18). `ec2-user` (the name in AWS's CLI example and the template's former default) cannot be resolved on a new SVM, so `FileSystemUnixUser` is now a required parameter with no default. Omitting it stops with `Parameters: [FileSystemUnixUser] must have values` before any resource is created (checked with the config 3 and 4 templates) [Tested]. The name: the create API returned success and the access point went to FAILED about 45 seconds later (5.4) [Tested]. The two existing UNIX access points on this file system use `root` and are AVAILABLE [Tested: 2026-11-10]. Root authorizes every file, so it is not a recommended setup; a verification records it as a measurement condition. `FileSystemIdentity` cannot be changed after creation.
- Authentication is a container-side IAM role. Config 3 (ECS Fargate) uses the task role; Config 4 (EKS Fargate) uses IRSA (OIDC provider + IAM role + service account annotation).

**Avoiding the access point policy cycle**: if the task / IRSA role references the access point ARN and the access point policy references that role ARN, they cycle. In the same account, either the identity policy or the access point policy granting access is sufficient, so the access point policy's Principal is set to the account root and the role's identity policy scopes to the access point. VPC origin denies any request from outside the VPC.

**`Resource` in the access point policy**: S3 Control rejects `Resource: '*'` (`Invalid policy: Policy has invalid resource`; the stack went to `CREATE_FAILED` and rolled back) [Tested: 2026-11-10]. The resource must be the access point itself, so the template builds the access point ARN and its `/object/*` form with `Fn::Sub` from the literal name. It does not use `Fn::GetAtt`, so the policy does not depend on the resource it belongs to.

**IRSA trust condition (Config 4)**: the condition keys `<oidc-issuer>:aud` and `:sub` contain the issuer host, and CloudFormation cannot put an intrinsic function in a map *key*. So the template writes the trust policy as a JSON document wrapped in `Fn::Sub` and passes the issuer host (the issuer URL without `https://`) as a variable. The role is scoped to `aud` and to the `sub` of one namespace + service account from creation, with no manual step after deployment. This form has a working example on AWS re:Post [Documented] ([StringEquals with Sub in both key and value](https://repost.aws/questions/QUyqQ4VGzLRqKDZgI-RloR2A/cloudformation-stringequals-with-sub-in-both-key-and-value)). When deployed, a Pod under a different service account was refused with `AssumeRoleWithWebIdentity` AccessDenied (5.4) [Tested]. EKS Pod Identity cannot be used for Pods on Fargate, so Config 4 uses IRSA [Documented]. <!-- spoke-checked: pods -->

### 5.3 Object API constraints [Documented]

Because access is via the S3 SDK, the app must be written for object access. It cannot be used as a mounted file system. Main constraints (source: [Access point compatibility](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)):

- Maximum object size for uploads is 50 GiB.
- Storage class is FSX_ONTAP only; server-side encryption is SSE-FSX only.
- Not supported: versioning, Object Lock, lifecycle, conditional writes, Requester Pays, static website hosting, ACLs other than `bucket-owner-full-control`.
- CopyObject / UploadPartCopy are same-access-point and same-Region only.

### 5.4 Hands-on results for configs 3 and 4

**Scope**: 2026-11-10, ap-northeast-1, a disposable SVM and two volumes (UNIX style, 1 GiB) created on the existing Single-AZ FSx for ONTAP (128 MBps). The access points were attached to these two volumes only; no existing SVM, volume, or access point was touched. `FileSystemIdentity` was `root` (a measurement condition, not a recommended setup). One observation per item. The templates included the `Resource` fix from 5.2. This is a small-scale check; it does not cover performance, narrowing the export policy, Multi-AZ, concurrent writes from several clients, or large objects.

**Config 3 (ECS Fargate)**

| Item | Result [Tested] |
|---|---|
| First deployment | `CREATE_FAILED` at `AWS::FSx::S3AccessPointAttachment` (`Invalid policy: Policy has invalid resource`). The cause was `Resource: '*'` in the policy (5.2). After the fix: `CREATE_COMPLETE`, the access point AVAILABLE, and the service at steady state (1/1) |
| Write and read | From a Fargate task in a private subnet, PutObject / GetObject worked with both the alias and the ARN passed as `--bucket`. The sha256 of three objects (one with a prefix) matched before and after. ListObjectsV2 honored prefix and delimiter; StorageClass showed `FSX_ONTAP` and encryption `aws:fsx` |
| Persistence across tasks | A different task in a different AZ read all three objects and the hashes matched |
| Call from outside the VPC | AccessDenied even for an administrator IAM principal (explicit deny in the resource-based policy). The VPC-origin scoping works |
| Reusing the existing S3 Gateway endpoint | With `CreateS3GatewayEndpoint=false` the stack deployed without creating an endpoint, and the calls above succeeded |
| `FileSystemIdentity=ec2-user` (control) | On a new SVM the create API returned success, the Lifecycle went to FAILED about 45 seconds later, and the reason was that the user could not be looked up in ONTAP. Deleted and confirmed gone |

**From the NFS side (multiprotocol)**: the same volume was mounted on an EC2 host with the config 1 template (NFS v4.1, port 2049 only). Objects written through S3 appeared as files over NFS with matching sha256 (owner root, group daemon, mode 644). A file written over NFS was readable with S3 GetObject and appeared in ListObjectsV2. An NFS read about 28 seconds and another about 100 seconds after the S3 PutObject both saw the object. Visibility at shorter intervals was not measured [Not measured].

**Non-root user (config 3)**: checked on a separate disposable SVM and volume (UNIX style, 1 GiB). The SVM admin password was set at SVM creation. From an EC2 instance in the VPC, the local UNIX user `s3ap_app` (UID 1001) was created through the SVM management endpoint with the ONTAP REST API (`vsadmin`, `POST /api/name-services/unix-users`). A new SVM already has `root`, `nobody`, and `pcuser`. The volume used mode bits only: `app/` (owner 1001, 755), `shared-ro/` (root, 755, one existing file), `public.txt` (root, 644), and `secret.txt` (root, 600). Config 3 was deployed with `FileSystemUnixUser=s3ap_app`.

| Operation | Result [Tested] |
|---|---|
| Access point | AVAILABLE |
| PutObject / GetObject under `app/` | Succeeded. Over NFS the file showed owner 1001, mode 644 |
| PutObject at the volume root | AccessDenied (the root is root-owned, 755) |
| PutObject under `shared-ro/` | AccessDenied |
| GetObject of `public.txt` (644) and the existing file in `shared-ro/` | Succeeded (others have read permission) |
| GetObject of `secret.txt` (600, root-owned) | AccessDenied |
| DeleteObject | Denied by IAM. The task role was not granted `s3:DeleteObject`, so this does not test file permissions |

So specifying a user other than `root` narrowed reads and writes by the file mode bits, a layer separate from the access point policy.

One snag was on the ONTAP side. A `chown 1001` from an NFSv4.1 client left the owner as `nobody` (65534). After creating a user with the same UID and name (`s3ap_app`) on the client and running `chown s3ap_app` by name, the owner became 1001. The SVM's NFS ID domain matched the client's default (the VPC's internal DNS domain); it was changed to another value once and set back. I could not find an NFSv4 numeric IDs setting in this REST API version.

**Config 4 (EKS Fargate, Kubernetes 1.35)**

| Item | Result [Tested] |
|---|---|
| Deployment | `CREATE_COMPLETE`. Two CoreDNS Pods were Running on Fargate (the coredns add-on's `computeType` was `Fargate`, status ACTIVE). The Fargate profile for `kube-system` + `k8s-app=kube-dns` was enough; no manual step was needed |
| Write and read with IRSA | From a Pod under the annotated service account, PutObject / GetObject / ListObjectsV2 worked and the sha256 matched |
| Different service account (control) | With the same role ARN annotated, a Pod under a service account whose name differs from the trust `sub` got AccessDenied on `AssumeRoleWithWebIdentity` |
| No annotation (control) | No credentials were found and the call failed |
| Pod recreation | After deleting and recreating the Pod, the earlier object was readable with a matching hash |

After teardown, the SVM, volumes, backups, access points, VPC endpoints, OIDC providers, ECS / EKS clusters, CloudFormation stacks, the FSx security group ingress rules, and the network interface count in this VPC (72) matched the baseline.

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
| Out of CloudFormation scope | None (all CFn) | PV objects (kubectl) | None (all CFn) | Service account creation and annotation |

---

## 7. Static Verification Results [Tested / 2026-09-22]

Confirmed that `make cfn-lint` (cfn-lint, `templates/*.yaml`) passes with exit 0, covering the four templates plus the two existing ones. A `params/*.example.json` with dummy values was prepared for each template, and the keys were confirmed to match the template parameters (the new-network CIDR parameters in Config 1 have defaults and are omitted when referencing existing resources).

**What this verification does not say**: configs 3 and 4 have not been verified to deploy and work. The config 1 results are in 3.3 and the config 2 results in 4.3. The following are the items to confirm on real infrastructure; V1 is already confirmed for configs 1 and 2, and V2 for config 2.

| # | Item | Research / verification state (2026-09-22) |
|---|---|---|
| V1 | Deploying the four configurations and data connectivity | Config 2 was checked on 2026-10-29 (4.3) and configs 1, 3, and 4 on 2026-11-10 (3.3, 5.4) [Tested] |
| V2 | Current Trident EKS add-on name and version | On 2026-10-29 in ap-northeast-1, `netapp_trident-operator` existed, the default was v26.6.2-eksbuild.1, and the highest supported Kubernetes version was 1.36 [Tested]. Names and versions change, so reconfirm before deploying. Trident 26.10 and Kubernetes 1.37 are in 9.3 |
| V3 | Whether EKS Pod Identity works on Fargate | Resolved: it cannot be used for Pods on Fargate [Documented] ([Pod Identity restrictions](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html), checked 2026-11-10). This is why this memo uses IRSA |
| V4 | Mapping of the S3 access point UNIX user to ONTAP-side permissions | With `root` reads and writes worked, and with `ec2-user`, which the SVM cannot resolve, the access point went to FAILED. With a local SVM user (non-root), reads and writes were narrowed by the mode bits (5.4) [Tested]. The mapping with NFSv4 ACLs or Active Directory users (NTFS) has not been checked [Not measured] |
| V5 | Effective throughput via the S3 access point | Docs state "depends on the file system's provisioned throughput". Not measured [Not measured] |

### 7.1 Deployment prerequisites (the stage before hands-on verification)

Before confirming V1–V5 on real infrastructure, these are the prerequisites, order, pitfalls, and cleanup, framed to prevent rework. Real deployment incurs charges and changes a shared account, so obtain per-action approval when starting it.

**Prerequisite: FSx for ONTAP is outside this repository's templates** [Tested]. None of the five templates create `AWS::FSx::FileSystem` / `StorageVirtualMachine` / `Volume`; they reference an existing FSx for ONTAP. As stage 0 of deployment, provision the file system + SVM + volume first, and record the SVM NFS endpoint, the volume junction path, and the file system security group ID (passed to config 1's `FsxnSvmNfsEndpoint` / `FsxnVolumeJunctionPath` / `FsxnSecurityGroupId`).

**Confirmed design decisions (do not undo on real infra)**:

- Config 1's template explicitly sets `nfsvers=4.1` for the NFS mount [Tested]. That NFSv4.1 completes over the single port 2049, and that 111 / 635 / 4045-4049 are for NFSv3 and are not needed for v4.1-only, is stated in AWS documentation [Documented] (source: [Use NFS to mount FSx for ONTAP volume on Linux instance](https://repost.aws/knowledge-center/ec2-mount-fsx-ontap-nfs)). In this repository on 2026-11-10, the NFS v4.1 mount and reads and writes worked with the ingress left at 2049 only [Tested] (3.3, one observation).
- The S3 Access Point policy circular reference is already avoided by setting the Principal to the account root and scoping on the role's identity policy (5.2).

**Items to confirm before starting (mapped to the V numbers)**:

| Preparation | Related unverified item | How to confirm |
|---|---|---|
| Current Trident EKS add-on name / version | V2 | `aws eks describe-addon-versions --addon-name netapp_trident-operator`. On 2026-10-29 in ap-northeast-1 the default was v26.6.2-eksbuild.1, ahead of this memo's 25.02 reference [Tested] |
| S3 Access Point dual-layer authorization (IAM + file-system-level UNIX / Windows user) | V4 | Design the mapping between the access point's UNIX user and the ONTAP file permissions on real infra. The behavior of `root` and of a local UNIX user is recorded in 5.4; NFSv4 ACLs and Windows users are unchecked [Documented] |
| Availability in the target region | V1 in general | Second-generation FSx for ONTAP expanded to four regions + GovCloud in 2026-04. S3 Access Points support Tokyo (ap-northeast-1) [Documented]. Confirm availability in the region you use |
| IRSA trust condition (EKS Fargate) | V3 | The trust is scoped by `aud` / `sub` from creation (5.2). That the scoping works (a Pod under a different service account is refused) was confirmed on 2026-11-10 (5.4) [Tested] |

**Recommended deployment order**: start with the smallest, config 1 (ECS on EC2 + NFS, which is CloudFormation-complete, with no Trident and no S3 Access Points). Once the data path is confirmed (read/write to `/data` from a task), delete it, then proceed step by step to config 2 (apply Trident's Kubernetes objects via kubectl / Helm) and configs 3 / 4 (S3 Access Points, with the manual IRSA step).

**Pitfalls (the kind that force rework on real infra)**:

- The mount is an instance boot-time step, not something a task creates. If a task starts before the mount is present, the bind-mount target is empty (already noted in 3.2). Treat the mount as a precondition of startup.
- When using `ontap-san` (iSCSI) alongside the Amazon EBS CSI driver, blacklist EBS devices in `multipath.conf` or the node multipath will claim EBS (already noted in 4.2).
- Trident's StorageClass / PVC / TridentBackendConfig cannot be created by CloudFormation; apply them with kubectl / Helm after the stack completes (already noted in 4.2).
- The FSx API reflects the volumes that Trident creates on the ONTAP side with a delay. If you check for leftovers after teardown with the FSx API alone, you read "absent" right after creation and "still there" right after deletion. Check with the ONTAP REST API (reached from inside the VPC through the management LIF). The FSx API did not list the volumes at 23 seconds and at 11 minutes after creation, and listed them at 26 minutes. After the volumes were deleted on ONTAP, the FSx API still listed them at 41 minutes and no longer did at 44 minutes [Tested: 2026-10-29, ap-northeast-1, 1 observation]. While the FSx API showed a non-root volume, deleting the SVM was rejected with `BadRequest`.

**Cleanup (a verification environment is exactly where you must delete)**: the main resources that keep charging are the FSx for ONTAP file system (hourly for SSD capacity + provisioned throughput), the EKS cluster, EC2 nodes / container instances, and NAT / VPC endpoints. After verification, delete the stack, and do not forget the FSx for ONTAP created outside the templates. A verification resource you cannot delete becomes a long-running charge and blocks operations on resources beside it.

**Teardown order with Trident**: before deleting the stack, delete the application Deployment, the PVCs (SAN and NAS separately), the StorageClasses, and the TridentBackendConfigs in that order. If a PV has reclaim policy `Retain`, deleting the PV object leaves Trident's record, so remove it with `tridentctl delete volume` before deleting the TridentBackendConfig (4.3). Then confirm with the ONTAP REST API that the LUN and the volumes are gone from ONTAP. Then delete the stack. If you created a dedicated SVM for the check, delete it once the FSx API no longer shows a non-root volume.

---

## 8. The Split Decision

If hands-on verification confirms feasibility, this set of artifacts (CloudFormation for the four configurations plus app-side change examples) has room to be split into a separate repository / Kiro project from the EC2 rehost verification (existing), because the target is source code and containers and the verification stack (ECS / EKS / Trident / S3 Access Points) is a different lineage from VMware migration. Whether to split is decided after hands-on verification.

---

## 9. EKS and Container Updates, October–November 2026, and Their Effect on These Configurations

**Scope of the survey**: on 2026-11-10 I read in full the EKS User Guide document history (entries from 2026-10-10 on), the two AWS What's New posts (DRA, Gateway API), the official documentation for each feature, and the NetApp Trident 26.10 release notes and requirements page. For KubeCon North America 2026 (Nov 9–12) I saw only search-result summaries, not the announcements themselves [Not measured]. The same day in ap-northeast-1 I checked the EKS add-on versions (9.3), Nitro Sandbox with Trident PVs (9.1), and Auto Mode with Trident (9.2) on real infrastructure. Everything else below is [Documented]; nothing else here was run in this repository.

Trident driver choice (`ontap-nas` vs `ontap-san`, and the Windows-nodes-only SMB PV) is in the hub's [container data store selection](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/reference/decision-trees/container-datastore-selection.md). That page does not cover Nitro Sandbox, Auto Mode, or Trident 26.10, so this chapter is the delta. <!-- spoke-checked: ontap-nas -->

| Update | Effect on config 2 (EKS on EC2 + Trident) | Effect on configs 3 / 4 (Fargate + S3 Access Points) |
|---|---|---|
| Per-pod isolation with Nitro Sandbox (`isolated-sandbox` / `confidential-sandbox`) | 9.1 | 9.1 |
| DRA support in EKS Auto Mode and Karpenter | 9.2 | None |
| Trident 26.10 and Kubernetes 1.37 | 9.3 | None |
| Auto Mode Gateway API, Argo CD capability updates, `ec2:CopyVolumes` | 9.4 | None |

### 9.1 Isolated pods with Nitro Sandbox, and storage

Each pod runs in its own Nitro Sandbox (a Firecracker microVM), selected per pod with `runtimeClassName`. Pods that do not set it keep the default runtime. It applies only to nodes on EC2 and has no bearing on Fargate pods (source: [Sandboxing on Amazon EKS](https://docs.aws.amazon.com/eks/latest/userguide/sandboxing.html)).

The documented storage options are (source: [Storage with Nitro Sandboxes](https://docs.aws.amazon.com/eks/latest/userguide/sandboxing-storage.html)):

- Amazon EBS CSI: attached to the sandbox as a block device. Use `ReadWriteOncePod`; one volume cannot be shared by several pods.
- Amazon EFS CSI (add-on 3.5.0 or later): the NFS mount and TLS termination happen inside the sandbox.
- CSI drivers backed by tmpfs (Secrets Store, cert-manager), plus `emptyDir` / ConfigMap / Secret.

**NFS and iSCSI PVs from Trident (`csi.trident.netapp.io`) are not mentioned on that page.** It does not say they are unsupported either, so the documentation does not settle whether they work. I tested it on real infrastructure.

![Figure 4: In an Amazon EKS Auto Mode cluster, two normal pods mounted a NetApp Trident NFS PersistentVolume, an isolated pod with isolated-sandbox failed to mount the same PersistentVolume, and it mounted Amazon EBS. The NFS PersistentVolume is on Amazon FSx for NetApp ONTAP](../_assets/images/s3ap-sandbox-storage-en.svg)

Figure 4: The storage an isolated pod could mount, and the storage it could not. The pod and PersistentVolume icons are [Kubernetes community icons](https://github.com/kubernetes/community/tree/main/icons) (Apache-2.0); the Trident logo is from the [NetApp/trident](https://github.com/NetApp/trident) repository

**Results** [Tested: 2026-11-10, ap-northeast-1, one observation per case]. On an EKS Auto Mode cluster (Kubernetes v1.36.4, Trident add-on v26.6.2-eksbuild.1), I mounted the same NFS PVC (RWX, 1 GiB, disposable SVM) into normal pods and into a pod with `runtimeClassName: isolated-sandbox`.

| Case | Result |
|---|---|
| Two normal pods (on different nodes) mount the NFS PVC | Worked. A marker written by one was read by the other |
| An isolated pod mounts the same NFS PVC | **Failed.** Container creation stopped with `failed to fulfil mount request: open …/volumes/kubernetes.io~csi/pvc-…/mount: no such file or directory`, ending in `CrashLoopBackOff` after 5 restarts in about 6 minutes. Provisioning and attach had succeeded |
| Control: an isolated pod using only `emptyDir` | Worked. The kernel inside the pod was 6.18.54 against 6.18.56 on the normal node, so it runs on a separate kernel |
| Control: an isolated pod mounts an Amazon EBS PVC (the Auto Mode EBS CSI) | Worked. Write and read-back succeeded |

Isolated pods worked on the same cluster and node type (c8a.large), and an EBS PVC mounted. Only the Trident NFS PV failed. That matches the fact that the storage page does not list Trident. AWS's sample collection has three blueprints for persistent storage in isolated pods: `ebs`, `efs`, and `s3-files` (source: [sample-eks-nitro-sandbox storage](https://github.com/aws-samples/sample-eks-nitro-sandbox/tree/main/examples/storage)). I found no published procedure for using FSx for ONTAP as persistent storage for an isolated pod. AWS's [Containers Blog](https://aws.amazon.com/blogs/containers/aws-nitro-sandboxes-hardware-enforced-workload-isolation-on-amazon-eks/) says CSI volumes are delivered into the VM the same way they reach a regular pod, yet the Trident NFS PV was not delivered in this observation. The [Compute Blog](https://aws.amazon.com/blogs/compute/nitro-sandboxes-hardware-isolation-for-every-eks-pod-ecs-task-and-ec2-workload/) says a sandbox reaches storage the same way an EC2 instance does (EBS for persistent volumes, S3 and EFS over the network). Calling S3 Access Points from an isolated pod with the S3 SDK reads as within that statement, but it was not tried [Not measured] (both read on 2026-11-11). I did not isolate the cause (for example, NodePublish completing on the host while the mount path never reaches the sandbox is a guess); Trident's info-level log has no record of it. This is one observation; reproduction and behavior on other versions are unconfirmed.

Whether an iSCSI PV can be handed to an isolated pod was not tested, because iSCSI itself was unavailable on the Auto Mode node (9.2). A pod with `sandbox.amazonaws.com/network-isolated: "true"` has no network device, and the page states that EFS is unavailable. I infer that network-reached FSx for ONTAP is unreachable for the same reason, but I did not test it.

**Public tracking** [filed 2026-11-10]. The page opens by saying storage works through "standard Kubernetes CSI drivers" and does not mention NFS volumes from a third-party CSI driver. I filed the clarification as [documentation feedback](https://github.com/awsdocs/amazon-eks-user-guide/issues/1259), NFS volume support as a [feature request](https://github.com/aws/containers-roadmap/issues/2911), and iSCSI / NVMe/TCP block volume support as a [separate feature request](https://github.com/aws/containers-roadmap/issues/2912). The block request states that iSCSI and NVMe/TCP in an isolated pod were not tested. Filing an issue does not mean AWS accepted or prioritized it.

The S3 Access Points object API used by configs 3 and 4 is an SDK call over the network, so in principle a sandboxed pod can use it. Authentication needs care. In isolated mode the service account token is not replicated into the sandbox, and IMDS returns no credentials (only five placement paths respond). EKS Pod Identity credentials are allowed. I have not confirmed that config 4's IRSA (which uses the service account token) works in an isolated-mode pod; a Pod Identity design is the straightforward one on paper. As V3 notes, Pod Identity on Fargate is separately not measured.

The sandbox limitations (startup failure with `hostNetwork: true`, no `hostUsers: false`, no GPU, a per-node vCPU density cap, and so on) probably do not apply to Trident's node pod itself, because that pod uses the normal runtime and only application pods select the sandbox. The documentation does not say this explicitly.

### 9.2 DRA in Auto Mode and Karpenter

DRA (Dynamic Resource Allocation) covers NVIDIA GPUs and EFA, not storage devices (source: [What's New](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-eks-auto-mode-karpenter-dra/)). How FSx for ONTAP PVs are provisioned and reached does not change. DRA in Auto Mode needs Kubernetes 1.36 or later; in Karpenter it applies to all versions.

There is one indirect effect. For a GPU-backed AI workload that keeps shared data on FSx for ONTAP, Auto Mode managed nodes do not let you install software (AWS chooses the AMI, and there is no SSH), which conflicts with config 2's iSCSI node preparation (the launch template in 4.2) (source: [Learn about Amazon EKS Auto Mode Managed instances](https://docs.aws.amazon.com/eks/latest/userguide/automode-learn-instances.html)). So this repository's `PrepareNodesForIscsi` approach cannot be applied to Auto Mode nodes. No document I read stated whether Trident works on Auto Mode, so I tested it on the same cluster as in 9.1.

**Results** [Tested: 2026-11-10, ap-northeast-1, one observation per case. Kubernetes v1.36.4, nodes on Bottlerocket (EKS Auto, Standard) 2026.10.31, Trident add-on v26.6.2-eksbuild.1].

| Case | Result |
|---|---|
| Installing the Trident add-on | With no nodes, pending pods made Auto Mode launch a node, and the node pod and controller reached Running. While the node started, the add-on showed `DEGRADED` (`InsufficientNumberOfReplicas`), which cleared once the node was up |
| Backends (one NFS, one iSCSI) and PVC provisioning | Both `Success` / `Bound`. Provisioning is done by the controller and needs no tools on the node |
| Mounting the NFS PV in a pod | **Worked.** Pods on two nodes shared a marker. On a new node it failed for tens of seconds with `CSINode … does not contain driver` until the Trident node pod registered, then succeeded |
| Mounting the iSCSI PV in a pod | **Failed.** `unable to attach: open-iscsi tools not found on host`. `tridentctl get node` showed empty IQN and SERVICES, and the log said `Could not read initiatorname.iscsi; perhaps iSCSI is not installed?` |

So on Auto Mode managed nodes an NFS PV works and an iSCSI PV does not. Because you cannot choose the AMI or install software on the node, config 2's `PrepareNodesForIscsi` approach cannot fill the gap. If you need iSCSI (block), use nodes whose AMI you control, such as a managed node group. This is one observation on Auto Mode and may change with a later AMI.

### 9.3 Trident 26.10 and Kubernetes 1.37

- EKS added Kubernetes 1.37 on 2026-10-01 (source: [Document history](https://docs.aws.amazon.com/eks/latest/userguide/doc-history.html)). Trident 26.10 supports Kubernetes 1.27 through 1.37 (source: [Trident requirements](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html)). The template's `KubernetesVersion` pattern accepts 1.37.
- The EKS add-on used in the 4.3 and V2 checks defaulted to v26.6.2-eksbuild.1, supporting Kubernetes up to 1.36 (2026-10-29) [Tested]. Rechecked on 2026-11-10 in ap-northeast-1: the newest add-on is still v26.6.2-eksbuild.1 (the default), supporting Kubernetes up to 1.36. There is no 26.10.x add-on yet and no build that supports 1.37 [Tested: 1 observation]. The same day, EKS had 1.34 through 1.37 in standard support. So the config 2 template, which uses the add-on, should be given Kubernetes 1.36 or lower for now. Using Trident 26.10.1 on 1.37 would mean installing it with the Helm trident-operator chart instead of the add-on. The sibling repository blea-fsxn-usecase has a [sample](https://github.com/Yoshiki0705/blea-fsxn-usecase/blob/main/usecases/blea-guest-fsxn-modernization-sample/doc/README.md) with the Helm install commands, but I found no run record for Trident 26.10.1 on Kubernetes 1.37, and I have not tried it here. <!-- spoke-checked: helm -->
- **Do not upgrade to Trident 26.10 before 26.10.1.** Per the release notes, at startup the node pods can detach volumes that are still in use, and pods fail with `volume … is not staged`. This is fixed in 26.10.1 (source: [Trident release notes](https://docs.netapp.com/us-en/trident/trident-rn.html)). When pinning the add-on version, pick 26.10.1 or later.
- 26.10 changes that touch the configurations here (as listed in the release notes; not run in this repository): ONTAP autosize on new volumes for `ontap-san` / `ontap-san-economy`, volume expansion when not all iSCSI paths are available, a fix for ONTAP-NAS export policy rules being deleted by mistake when `enableConcurrency` is true, and the PVC annotation `trident.netapp.io/unixGroupID` (ONTAP-NAS volumes with root squash).

### 9.4 Other updates relevant to operating config 2

- Gateway API in EKS Auto Mode (2026-10): ALB / NLB traffic control; it does not touch the storage path.
- EKS Capability for Argo CD notifications, the ApplicationSet webhook, and the source hydrator (2026-10 to 11): as 4.2 says, TridentBackendConfig / StorageClass / PVC cannot be created by CloudFormation and are applied with kubectl or similar after the stack completes. Applying them through GitOps is a possible option, but I have not tried it here. <!-- spoke-checked: helm -->
- `ec2:CopyVolumes` (2026-10-26): lets the Auto Mode EBS CSI create a PVC from an existing PVC without a snapshot. It applies to EBS volumes and does not involve FSx for ONTAP PVs.

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
- [Sandboxing on Amazon EKS with isolated and confidential pods](https://docs.aws.amazon.com/eks/latest/userguide/sandboxing.html)
- [Storage with Nitro Sandboxes](https://docs.aws.amazon.com/eks/latest/userguide/sandboxing-storage.html)
- [Amazon EKS Auto Mode and Karpenter now support Dynamic Resource Allocation](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-eks-auto-mode-karpenter-dra/)
- [Learn about Amazon EKS Auto Mode Managed instances](https://docs.aws.amazon.com/eks/latest/userguide/automode-learn-instances.html)
- [Amazon EKS User Guide: Document history](https://docs.aws.amazon.com/eks/latest/userguide/doc-history.html)
- [Trident release notes](https://docs.netapp.com/us-en/trident/trident-rn.html)
- [Trident requirements](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html)
- [Containerization Derivation and FSx for ONTAP Integration (this repository)](atx-containerization-fsxn-derivation.md)
