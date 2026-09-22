# Mounting FSx for ONTAP on ECS on EC2

**Purpose**: Cover comprehensively how to use Amazon FSx for NetApp ONTAP as a container data area on the Amazon ECS EC2 launch type, centered on the AWS official host-mount methods (NFS / SMB). Also determine from primary sources whether NetApp Trident can be introduced as a container on ECS on EC2, recording confidence levels separately.

**Last Updated**: 2026-09-22
**Status**: Literature research + documentation. No hands-on mount verification (Trident-on-ECS hands-on verification is planned for the next stage)

Related: this document drills the Config 1 of [Verifying FSx for ONTAP Data Store Configurations on Container Targets](atx-containerization-fsxn-storage-verification.md) down to the procedure level.

---

## 1. Conclusion

The established way to use FSx for ONTAP on ECS on EC2 is for the **EC2 container instance to mount the volume and bind-mount it into the task** (source: [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html)).

| Path | Access form | Container OS | Confidence |
|---|---|---|---|
| Linux + NFS | Host mounts NFS → bind mount via `host.sourcePath` | Linux | [Documented] |
| Windows + SMB | Host SMB global mapping → bind mount | Windows | [Documented] |
| Via Trident (Docker plugin) | Trident as the host's Docker volume driver → referenced by the task definition `dockerVolumeConfiguration` | Linux | [Unverified] |

**Correction about Trident**: earlier in this project it was stated that "Trident is Kubernetes-only and cannot be used on ECS." That was wrong. Trident is also offered as a Docker volume plugin and does not depend on Kubernetes (Section 3). Introducing it on ECS on EC2 is feasible in principle, but no statement that AWS or NetApp officially supports/tests the "ECS + Trident Docker plugin" combination was found as of this research (2026-09-22). It is therefore [Unverified], and hands-on verification is placed in the next stage (Section 5).

---

## 2. Evidence Tiers

| Tag | Meaning |
|---|---|
| **[Verified]** | Actually executed and confirmed in this repository |
| **[Documented]** | Stated in AWS / NetApp official documentation. Source URL included. Does not imply hands-on confirmation |
| **[Unverified]** | Not executed and not corroborated by public information. Investigation date and scope included |

---

## 3. AWS Official Host-Mount Methods

### 3.1 Linux containers and NFS [Documented]

The procedure is in this order (source: the ECS User Guide above).

1. Create an ECS cluster with the EC2 Linux + Networking cluster template.
2. Create a mount target directory on the container instance (e.g. `/fsxontap`).
3. Mount the SVM volume over NFS, via instance user-data or a manual command.

```
sudo mount -t nfs -o nfsvers=4.1 svm-dns-name:/volume-junction-path /fsxontap
```

4. Add `volumes` (`host.sourcePath`) and `mountPoints` to the task definition to bind-mount the host mount into the container.

### 3.2 NFS mount defaults and notes [Documented]

- FSx for ONTAP NFS mounts are **hard mounts** by default. To make failover smooth, the default hard mount is recommended (source: [Mounting volumes on Linux clients](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/attach-linux-client.html)).
- You can mount by the SVM DNS name or IP. The NFS version is set with `nfsvers`.
- ONTAP limits NFS I/O size to 64K by default [Documented] (source: [PostgreSQL databases with NFS Filesystems](https://docs.netapp.com/us-en/ontap-apps-dbs/postgres/postgres-nfs-filesystems.html)).

### 3.3 Windows containers and SMB [Documented]

1. Create an ECS cluster with the EC2 Windows + Networking cluster template.
2. Add a domain-joined EC2 Windows instance and initialize the ECS agent with `Initialize-ECSAgent -Cluster <cluster> -EnableTaskIAMRole`.
3. Map the SMB share to a drive (e.g. `Z:`) with `New-SmbGlobalMapping`. The same volume (`vol1`) mounted over NFS can be exposed as a CIFS share.
4. Add `volumes` and `mountPoints` to the task definition to bind-mount into the container.

### 3.4 Network and security groups [Documented]

- Allow NFS on port 2049 and SMB on port 445 from the ECS instances to the FSx for ONTAP security group.
- Place FSx for ONTAP and the ECS instances in mutually reachable VPCs. Reachability to the SVM endpoint (DNS / IP) is a prerequisite.

### 3.5 Mount lifecycle [Documented + Unverified]

- The mount is a container instance action (user-data / `fstab`), not something the task creates.
- **If a task starts before the mount, the bind-mount target is empty** [documented implication]. Treat the mount as a launch prerequisite. How to handle a task on mount failure (retry, health check) is an operational design concern, and the actual behavior is unverified [Unverified].

### 3.6 Authentication and permissions [Documented + Unverified]

- Linux + NFS: because the host mounts over NFS, file access follows the host UID/GID and the ONTAP export policy. The task role (IAM) is not involved in the mount itself.
- Windows + SMB: the SVM joins Active Directory and SMB authentication uses AD credentials. For AD-join prerequisites, see the [AD integration procedure](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/en/ad-integration-for-migration.md) in the separate repository.
- The concrete mapping of NFS UID/GID to ONTAP-side permissions needs hands-on confirmation [Unverified].

### 3.7 Relationship with the ECS daemon mechanisms [Documented]

As a follow-on from the earlier discussion, ECS has two mechanisms to place a resident task per host.

- **daemon scheduling strategy**: a service's `schedulingStrategy: DAEMON`. On the EC2 launch type it places one task on each container instance.
- **ECS Managed Daemons**: a newer capability that places and manages one daemon task on each EC2 instance of an Amazon ECS Managed Instances capacity provider. Intended for logging, tracing, and security agents (source: [Amazon ECS Managed Daemons](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-daemons.html)).

Both are ways to place an ECS task on each instance and do not provide a Kubernetes CSI runtime. The NFS/SMB host-mount methods (3.1–3.3) do not need a daemon mechanism. The instance bootstrap mount is sufficient.

### 3.8 Constraints and alternatives [Documented]

- This method is EC2-launch-type only. Fargate cannot mount to a host, so it cannot use it (Fargate uses object access via S3 Access Points. See Configs 3 / 4 in the [verification memo](atx-containerization-fsxn-storage-verification.md)).
- The ECS + FSx for Windows File Server combination is Windows EC2 only — Linux EC2 and Fargate are out of scope (source: [Use FSx for Windows File Server volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/wfsx-volumes.html)). This document targets FSx for ONTAP.
- Because it is a bind mount, multiple tasks share the same host mount. The sharing granularity is per host.

---

## 4. The Path of Introducing Trident as a Container

### 4.1 Existence of Trident for Docker [Documented]

Trident is offered not only as a Kubernetes CSI driver but also as a **Docker volume plugin** (source: [Deploy Trident for Docker](https://docs.netapp.com/us-en/trident/trident-docker/deploy-docker.html)). It does not depend on Kubernetes. A passage in the requirements documentation describes this: Trident is a process that runs in a container and runs on any Linux worker; the actual volume mount is handled by the worker's standard NFS client / iSCSI initiator (source: [Requirements](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html)).

Key points of the Docker managed plugin method:

```
docker plugin install --grant-all-permissions --alias netapp \
  netapp/trident-plugin:<version> config=myConfigFile.json
docker volume create -d netapp --name firstVolume
docker run --rm -it --volume-driver netapp --volume secondVolume:/my_vol alpine ash
```

The config file (`/etc/netappdvp/config.json`) specifies `storageDriverName` (`ontap-nas` / `ontap-san`), `managementLIF` / `dataLIF`, `svm`, `username` (`vsadmin`), and `aggregate`.

### 4.2 ECS Docker volume driver support [Documented]

An ECS on EC2 task definition can specify a **third-party Docker volume driver** via `dockerVolumeConfiguration`'s `driver` (source: [Use Docker volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/docker-volumes.html)). Constraints:

- Docker volumes are **EC2-launch-type only**. Fargate is unsupported.
- Windows containers support only the `local` driver.
- The volume is managed by Docker, and a data directory is created in `/var/lib/docker/volumes` on the container instance.

### 4.3 Assessment of combining the two [Unverified]

Combining 4.1 and 4.2, the following path is feasible in principle.

1. Install the Trident Docker plugin on the ECS EC2 container instance (`docker plugin install netapp/trident-plugin`).
2. Configure FSx for ONTAP as the backend (`storageDriverName: ontap-nas` etc., specifying the SVM LIFs).
3. Reference `driver: netapp` in the task definition `dockerVolumeConfiguration` to mount the volume into the container.

FSx for ONTAP is listed as a supported Trident backend (source: [Requirements, Supported backends](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html)).

**However, no statement that AWS or NetApp officially supports/tests this combination was found as of this research (2026-09-22)** [Unverified]. Scope searched: the ECS documentation (docker-volumes.html, specify-volume-config.html), the Trident Docker deploy procedure, and the Trident requirements page. Therefore:

- We can say up to "it is feasible by combining two documented mechanisms (ECS third-party volume driver, Trident for Docker)".
- We have **not** confirmed that "ECS + Trident Docker plugin + FSx for ONTAP works". There is no corroboration of official support.

Blurring this distinction invites wrong design decisions. Until hands-on verification (Section 5), treat it as [Unverified].

### 4.4 Difference from the NFS host-mount method [Documented + Unverified]

| Aspect | NFS host mount (Section 3) | Trident Docker plugin (Section 4) |
|---|---|---|
| Volume creation | Create the volume on ONTAP in advance; the host mounts it manually | Trident provisions on demand (`docker volume create`) |
| Control plane | OS mount / fstab | Trident (`docker volume` / config file) |
| Dynamic provisioning | None (static) | Yes (Trident provisions) |
| Official support stated | Yes (AWS ECS User Guide) [Documented] | Not found [Unverified] |
| ONTAP features (snapshot/clone) | Operated separately on ONTAP | Potentially usable as Trident driver features (unverified) |

If you do not need dynamic provisioning or ONTAP feature integration, the established NFS host-mount method suffices. If you need the Trident Docker plugin path's benefits (dynamic provisioning, etc.), confirm feasibility in the next-stage hands-on verification.

---

## 5. Hands-On Verification of Trident on ECS (Next-Stage Design)

This session does not perform hands-on verification. Here is the design of the steps to run if feasibility is confirmed. Before execution, obtain individual approval because it involves launching EC2 instances, connecting to FSx for ONTAP, and changing a shared verification account.

1. **Preparation**: an ECS on EC2 cluster (the existing [Config 1 template](../../templates/containers-ecs-ec2-fsxn-nfs.yaml) can serve as a base), an FSx for ONTAP file system and SVM, the SVM management LIF / data LIF, and `vsadmin` credentials (Secrets Manager).
2. **Plugin install**: run `docker plugin install netapp/trident-plugin:<version> config=...` in the container instance bootstrap. Configure the FSx for ONTAP SVM and `ontap-nas` (or `ontap-san`).
3. **Task definition**: set `driver: netapp` in `dockerVolumeConfiguration` and confirm whether `autoprovision` is needed.
4. **Verification items**:
   - Whether the plugin connects to FSx for ONTAP and can provision/mount a volume.
   - When using `ontap-san` (iSCSI), whether the node multipath configuration and EBS conflict (need to blacklist EBS in `multipath.conf`) can be avoided.
   - Mount reproduction on task restart and instance replacement.
   - The operational difference from the NFS host-mount method (Section 3) (dynamic provisioning, ONTAP features).
5. **Record**: reflect worked / did not work / conditionally worked in Section 4.3 of this document, updating [Unverified] to [Verified].

---

## 6. Unverified Items

| # | Item | Research / verification state (2026-09-22) |
|---|---|---|
| E1 | Feasibility of ECS + Trident Docker plugin + FSx for ONTAP integration | Feasible in principle (4.3). No official support statement found. Not verified on hardware [Unverified] |
| E2 | Actual ECS task behavior on mount failure | Not verified. An operational design concern [Unverified] |
| E3 | Concrete mapping of NFS UID/GID to ONTAP export policy | To confirm on hardware [Unverified] |
| E4 | EBS multipath conflict avoidance when using `ontap-san` with the Trident Docker plugin | Blacklisting is known to be required on the Kubernetes path. Behavior on the Docker plugin path is not verified [Unverified] |

---

## Reference Links

- [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html)
- [Mounting volumes on Linux clients (FSx for ONTAP)](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/attach-linux-client.html)
- [Use FSx for Windows File Server volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/wfsx-volumes.html)
- [Amazon ECS Managed Daemons](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-daemons.html)
- [Use Docker volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/docker-volumes.html)
- [Specify a Docker volume in an Amazon ECS task definition](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specify-volume-config.html)
- [Deploy Trident for Docker](https://docs.netapp.com/us-en/trident/trident-docker/deploy-docker.html)
- [Trident Requirements (supported frontends / backends)](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html)
- [Verifying FSx for ONTAP Data Store Configurations on Container Targets (this repository)](atx-containerization-fsxn-storage-verification.md)
- [AD integration procedure (separate repository VMware-Migration-EC2-ONTAP)](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/en/ad-integration-for-migration.md)
