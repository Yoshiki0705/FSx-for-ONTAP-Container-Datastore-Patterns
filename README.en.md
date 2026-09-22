# FSx for ONTAP as a Container Data Store — 5 Patterns for ECS / EKS

🌐 [日本語](README.md) | 📚 Hub: [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook)

Configuration patterns and CloudFormation templates for using Amazon FSx for NetApp ONTAP as the data area for containers on Amazon ECS / Amazon EKS, including workloads modernized with AWS Transform containerization.

## TL;DR

- **Audience**: teams migrating VMware / .NET / Java workloads to ECS or EKS who want FSx for ONTAP as the data store.
- **Scope**: NFS/SMB host mount on ECS EC2, NetApp Trident persistent volumes (PV) on EKS EC2, and S3 Access Points object access on ECS/EKS Fargate.
- **Keywords**: FSx for ONTAP, Amazon ECS, Amazon EKS, AWS Fargate, NFS, SMB, NetApp Trident, S3 Access Points, CloudFormation, AWS Transform.
- **Status**: literature research + CloudFormation + static verification (cfn-lint). Hands-on deployment is the next stage.
- **General ONTAP knowledge** (block PV volume limits, multipath, driver choice) lives in the hub, [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook). This repository focuses on the container data-store integration.

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
