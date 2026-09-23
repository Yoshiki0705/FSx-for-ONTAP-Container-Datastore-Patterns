# FSx for ONTAP as a Container Data Store — 5 Patterns for ECS / EKS

🌐 [日本語](README.md) | 📚 Hub: [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook)

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Yoshiki0705/FSx-for-ONTAP-Container-Datastore-Patterns/badge)](https://scorecard.dev/viewer/?uri=github.com/Yoshiki0705/FSx-for-ONTAP-Container-Datastore-Patterns)

Configuration patterns and CloudFormation templates for using Amazon FSx for NetApp ONTAP as the data area for containers on Amazon ECS / Amazon EKS, including workloads modernized with AWS Transform containerization.

## TL;DR

- **Audience**: anyone who needs a persistent data area for containers on ECS / EKS — whether building new, choosing storage for existing containers, or migrating from legacy. Workloads in scope include .NET Framework / .NET Core, Java / Spring Boot, Windows / SMB-dependent apps, database and StatefulSet persistence, content delivery / media processing / analytics shared across multiple Pods, and multiprotocol (NFS / SMB / S3) shared-data platforms. Migration from VMware is treated as one path among these.
- **Scope**: NFS/SMB host mount on ECS EC2, NetApp Trident persistent volumes (PV) on EKS EC2, and S3 Access Points object access on ECS/EKS Fargate.
- **Keywords**: FSx for ONTAP, Amazon ECS, Amazon EKS, AWS Fargate, NFS, SMB, NetApp Trident, S3 Access Points, CloudFormation, AWS Transform.
- **Status**: literature research + CloudFormation + static verification (cfn-lint). Hands-on deployment is the next stage.
- **General ONTAP knowledge** (block PV volume limits, multipath, driver choice) lives in the hub, [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook). This repository focuses on the container data-store integration.

## Migration Approach Positioning

There is more than one path for bringing an existing workload to AWS. They divide into three by "how far you modernize," and all three can land the data on FSx for ONTAP. If you are building new containers with no migration involved, skip this table and go to the five-configuration matrix.

| Approach | What it does | Example tool | Landing on AWS | Reach from containers | Maturity |
|---|---|---|---|---|---|
| Replatform (containerize) | Dockerize source code onto ECS / EKS | AWS Transform containerization | Containers on ECS / EKS | Trident PV (NFS / iSCSI) / host NFS. Not Fargate | GA [Documented] |
| Rehost (VM as-is on EC2) | Move the VM to EC2 and separate the data onto FSx for ONTAP | AWS Transform for migrations (MGN) | EC2 + FSx for ONTAP | A container later reaches the same FSx for ONTAP over iSCSI / NFS | GA [Documented] |
| Third-party VM → EC2 | Convert OS disks to EBS and data disks to FSx for ONTAP, onto EC2 | NetApp Shift Toolkit v8.0 | EC2 + FSx for ONTAP | Same as above; file-to-LUN can also switch file → block | Early Preview (contact support) [Documented] |

**.NET modernization is possible from source code** [Documented]. AWS Transform converts .NET Framework 3.5 / .NET Core 3.1–.NET 10 to .NET 8 / .NET 10, making it cross-platform and Linux-container-ready (C# / VB.NET (preview); ASP.NET MVC / Web API / Web Forms, etc.). WinForms / WPF / Xamarin are preview; Blazor UI and Win32 DLLs without a compatible library are out of scope (as of 2026-09). See the [derivation document](docs/en/atx-containerization-fsxn-derivation.md) for the supported range.

**ONTAP's multiprotocol capability is a benefit common to all three paths** [Documented]. The same volume is reachable over NFS / SMB / S3, and switching protocols needs no data migration. A two-stage shape works: after rehost, a container reaches the data EC2 was using over a different protocol. Shift Toolkit v8.0's file-to-LUN (converting a file directly to block) is a concrete example — useful for switching from a fast, highly parallel file-based migration to single-writer block performance in operation. Motivations, use cases, and sources are in section 9 of the [derivation document](docs/en/atx-containerization-fsxn-derivation.md).

> **Maturity note**: Shift Toolkit v8.0's EC2 support is Early Preview as of 2026-09, and enabling EC2 as a target requires contacting NetApp support. Its maturity differs from the GA AWS Transform / MGN, so state this difference when relying on it in a design.

## Five-Configuration Fitness Matrix

| # | Runtime | FSx for ONTAP access form | App change | Template |
|---|---|---|---|---|
| 1 | ECS on EC2 | NFS mounted on the EC2 host → bind mount | None | [containers-ecs-ec2-fsxn-nfs.yaml](templates/containers-ecs-ec2-fsxn-nfs.yaml) |
| 1b | ECS on EC2 (Windows) | SMB global mapping → bind mount | None | [containers-ecs-ec2-fsxn-smb.yaml](templates/containers-ecs-ec2-fsxn-smb.yaml) |
| 2 | EKS on EC2 | NetApp Trident PV (NFS `ontap-nas` / iSCSI `ontap-san`) | None | [containers-eks-ec2-fsxn-trident.yaml](templates/containers-eks-ec2-fsxn-trident.yaml) |
| 3 | ECS on Fargate | S3 object API via S3 Access Points | Required (S3 SDK) | [containers-ecs-fargate-fsxn-s3ap.yaml](templates/containers-ecs-fargate-fsxn-s3ap.yaml) |
| 4 | EKS on Fargate | S3 object API via S3 Access Points | Required (S3 SDK) | [containers-eks-fargate-fsxn-s3ap.yaml](templates/containers-eks-fargate-fsxn-s3ap.yaml) |

Fargate cannot use FSx for ONTAP through a volume mount, so it uses object access via S3 Access Points. Keep file I/O on the EC2 launch type (1 / 2); take serverless operation on Fargate (3 / 4) — a trade-off.

## Documentation

- [Containerization Derivation and FSx for ONTAP Integration](docs/en/atx-containerization-fsxn-derivation.md)
- [Verifying FSx for ONTAP Data Store Configurations on Container Targets](docs/en/atx-containerization-fsxn-storage-verification.md)
- [Mounting FSx for ONTAP on ECS on EC2](docs/en/ecs-ec2-fsxn-mount.md)

## Gates

```bash
make install   # create .venv with pinned versions
make ci        # cfn-lint + headings + role-labels
```

## Related Repositories

- Hub: [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) — design, build, and operations knowledge for FSx for ONTAP
- [VMware-Migration-EC2-ONTAP](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap) — VMware → EC2 + FSx for ONTAP rehost migration verification. The AD that the SMB configuration references can be set up there
