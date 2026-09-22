# FSx for ONTAP をコンテナのデータストアにする — ECS / EKS の 5 パターン

🌐 [English](README.en.md) | 📚 Hub: [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook)

Amazon FSx for NetApp ONTAP を、Amazon ECS / Amazon EKS 上のコンテナのデータ領域として使うための構成パターンと CloudFormation テンプレート集です。AWS Transform のコンテナ化でモダナイズしたワークロードを含みます。

## TL;DR

- **対象読者**: VMware / .NET / Java などのワークロードを ECS・EKS へ移行し、FSx for ONTAP をデータストアに使いたい方。
- **扱う範囲**: ECS on EC2 の NFS/SMB ホストマウント、EKS on EC2 の NetApp Trident 永続ボリューム(PV)、ECS/EKS on Fargate の S3 Access Points 経由オブジェクトアクセス。
- **キーワード**: FSx for ONTAP, Amazon ECS, Amazon EKS, AWS Fargate, NFS, SMB, NetApp Trident, S3 Access Points, CloudFormation, AWS Transform。
- **現状**: 文献調査 + CloudFormation + 静的検証(cfn-lint)まで。実機デプロイは次段階。
- **一般的な ONTAP 知見**(ブロック PV のボリューム上限、マルチパス、ドライバ選択)は Hub の [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) にあります。本リポジトリはコンテナのデータストア連携に絞ります。

## 5 構成の適合表

| # | 実行環境 | FSx for ONTAP の到達形態 | アプリ改修 | テンプレート |
|---|---|---|---|---|
| 1 | ECS on EC2 | NFS を EC2 ホストにマウント → bind mount | 不要 | [containers-ecs-ec2-fsxn-nfs.yaml](templates/containers-ecs-ec2-fsxn-nfs.yaml) |
| 1b | ECS on EC2 (Windows) | SMB グローバルマッピング → bind mount | 不要 | [containers-ecs-ec2-fsxn-smb.yaml](templates/containers-ecs-ec2-fsxn-smb.yaml) |
| 2 | EKS on EC2 | NetApp Trident の PV(NFS `ontap-nas` / iSCSI `ontap-san`) | 不要 | [containers-eks-ec2-fsxn-trident.yaml](templates/containers-eks-ec2-fsxn-trident.yaml) |
| 3 | ECS on Fargate | S3 Access Points 経由のオブジェクト API | 必要(S3 SDK) | [containers-ecs-fargate-fsxn-s3ap.yaml](templates/containers-ecs-fargate-fsxn-s3ap.yaml) |
| 4 | EKS on Fargate | S3 Access Points 経由のオブジェクト API | 必要(S3 SDK) | [containers-eks-fargate-fsxn-s3ap.yaml](templates/containers-eks-fargate-fsxn-s3ap.yaml) |

Fargate はボリュームマウントで FSx for ONTAP を使えないため、S3 Access Points 経由のオブジェクトアクセスを使います。ファイル I/O を維持したい場合は EC2 起動タイプ(1・2)、サーバーレス運用なら Fargate(3・4)、というトレードオフです。

## ドキュメント

- [コンテナ化への派生と FSx for ONTAP の連携可否](docs/ja/atx-containerization-fsxn-derivation.md)
- [コンテナ移行先での FSx for ONTAP データストア構成の検証](docs/ja/atx-containerization-fsxn-storage-verification.md)
- [ECS on EC2 における FSx for ONTAP のマウント](docs/ja/ecs-ec2-fsxn-mount.md)

## ゲート

```bash
make install   # .venv を固定版で用意
make ci        # cfn-lint + headings + role-labels
```

## 関連リポジトリ

- Hub: [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) — FSx for ONTAP の設計・構築・運用知見
- [VMware-Migration-EC2-ONTAP](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap) — VMware → EC2 + FSx for ONTAP リホスト移行の検証。SMB 構成が参照する AD はこちらで用意できます
