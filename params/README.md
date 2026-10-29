# CloudFormation parameter files

Example parameter files for `aws cloudformation create-stack --parameters file://params/<file>.json`.
AWS CLI parameter JSON cannot carry comments, so the meaning of each value lives in this README.

## Usage

```bash
# Copy and fill in your own values
cp params/containers-eks-ec2-fsxn-trident.example.json params/my-eks-trident.json
vim params/my-eks-trident.json

# Deploy (the templates reference an existing FSx for ONTAP; they do not create one)
aws cloudformation create-stack \
  --stack-name eks-ec2-fsxn-trident \
  --template-body file://templates/containers-eks-ec2-fsxn-trident.yaml \
  --parameters file://params/my-eks-trident.json \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --region <your-region>
```

> **Security note**: a filled-in file holds your real IDs. Do not commit it. Keep only the
> `*.example.json` files in version control; name your copies something that is gitignored
> (for example `params/*.my.json`).

## Placeholder values to replace

| Placeholder | Replace with | How to obtain |
|---|---|---|
| `subnet-0123456789abcdef0` | Two private subnet IDs, in different AZs, in the VPC that hosts your FSx for ONTAP | `aws ec2 describe-subnets --filters Name=vpc-id,Values=<vpc-id> --query "Subnets[].[SubnetId,AvailabilityZone]" --output table` |
| `sg-0123456789abcdef0` | The security group of your FSx for ONTAP file system | `aws fsx describe-file-systems --query "FileSystems[].[FileSystemId,NetworkInterfaceIds]"` then look up the ENI's groups, or read it from the FSx console |
| `eks-ec2-fsxn-trident` | Your cluster name (optional) | choose any name |

## Parameter reference (EKS + Trident, config 2)

| ParameterKey | Example | Notes |
|---|---|---|
| `Subnet1Id`, `Subnet2Id` | two private subnets | Must be in the same VPC as the FSx for ONTAP file system and route to ECR and the Amazon Linux package repository (a NAT gateway or VPC endpoints). Use two different AZs. |
| `ClusterName` | `eks-ec2-fsxn-trident` | EKS cluster name. |
| `KubernetesVersion` | `1.35` | Pass a version that is in **standard support** on your deploy date. Check `aws eks describe-cluster-versions --query "clusterVersions[?versionStatus=='STANDARD_SUPPORT'].clusterVersion"`. The template has no default on purpose, so an extended-support version is never selected silently. The Trident add-on version you pick must support this Kubernetes version. |
| `NodeInstanceType` | `m5.large` | Managed node group instance type. |
| `NodeDesiredSize` | `2` | Node count. Two nodes in two AZs is enough to see a pod reschedule across nodes. |
| `PrepareNodesForIscsi` | `true` | Needed for `ontap-san` (iSCSI). The Amazon Linux 2023 EKS AMI ships `nfs-utils` but not the iSCSI/multipath tools, so a launch template installs them at first boot and writes `/etc/multipath.conf` (with the EBS devices blacklisted so multipath does not claim them). Set `false` only if you use `ontap-nas` (NFS) exclusively. |
| `FsxnSecurityGroupId` | your FSx SG | The template adds ingress to this SG from the EKS cluster security group. Managed node group nodes carry only the cluster security group, so the source must be the cluster SG, not a separate node SG. |
| `TridentAddonVersion` | `DEFAULT` | `DEFAULT` takes the current default of the `netapp_trident-operator` EKS add-on. To pin: `aws eks describe-addon-versions --addon-name netapp_trident-operator --query "addons[0].addonVersions[].addonVersion"`. |

## After the stack completes

CloudFormation creates the cluster, the node group, and the Trident add-on, but it cannot create
the Kubernetes objects that make a PersistentVolume appear (`TridentBackendConfig`, `StorageClass`,
`PersistentVolumeClaim`). Apply those with `kubectl`/Helm. See
`docs/{en,ja}/atx-containerization-fsxn-storage-verification.md` §4.2–4.3 for the backend, storage
class, and the verified behavior.

Two things worth knowing, both observed on a real cluster:

- **Node readiness order is not guaranteed.** `iscsid` and `kubelet` can start in the same second.
  If a Trident node pod starts before the iSCSI tools are in place, restart the
  `trident-node-linux` DaemonSet.
- **If you import an existing volume with reclaim policy `Retain`**, deleting the PVC and the PV
  leaves the ONTAP volume in place. Trident keeps its own record, so a later backend removal waits
  at "Backend is in a deleting state" until you run `tridentctl -n trident delete volume <pv-name>`.

## Using your existing cluster or storage class

These templates stand up a dedicated cluster for verification. If you already operate EKS:

- **Reusing an existing EKS cluster**: install the Trident add-on
  (`aws eks create-addon --addon-name netapp_trident-operator`) and add FSx-for-ONTAP ingress to
  your FSx security group from your cluster's security group. Skip this template's cluster/node
  group. Node preparation for iSCSI still applies — either bake the tools into your AMI or run them
  through your node bootstrap.
- **Reusing an existing `StorageClass`/CSI**: Trident coexists with other CSI drivers (for example
  the EBS CSI driver); the `multipath.conf` written here blacklists EBS devices so multipath does
  not claim them. Point a `StorageClass` at `csi.trident.netapp.io` for the volumes you want on FSx
  for ONTAP and leave your other storage classes as they are.

## File inventory

| File | Template |
|---|---|
| `containers-ecs-ec2-fsxn-nfs.example.json` | `templates/containers-ecs-ec2-fsxn-nfs.yaml` |
| `containers-ecs-ec2-fsxn-smb.example.json` | `templates/containers-ecs-ec2-fsxn-smb.yaml` |
| `containers-ecs-fargate-fsxn-s3ap.example.json` | `templates/containers-ecs-fargate-fsxn-s3ap.yaml` |
| `containers-eks-ec2-fsxn-trident.example.json` | `templates/containers-eks-ec2-fsxn-trident.yaml` |
| `containers-eks-fargate-fsxn-s3ap.example.json` | `templates/containers-eks-fargate-fsxn-s3ap.yaml` |
