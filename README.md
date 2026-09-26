# FSx for ONTAP をコンテナのデータストアにする — ECS / EKS の 5 パターン

🌐 [English](README.en.md) | 📚 Hub: [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook)

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Yoshiki0705/FSx-for-ONTAP-Container-Datastore-Patterns/badge)](https://scorecard.dev/viewer/?uri=github.com/Yoshiki0705/FSx-for-ONTAP-Container-Datastore-Patterns)

Amazon FSx for NetApp ONTAP を、Amazon ECS / Amazon EKS 上のコンテナのデータ領域として使うための構成パターンと CloudFormation テンプレート集です。AWS Transform のコンテナ化でモダナイズしたワークロードを含みます。

## TL;DR

- **対象読者**: ECS・EKS 上のコンテナに永続データ領域を用意したい方。新規構築でも、既存コンテナのストレージ選定でも、レガシーからの移行でも構いません。想定するワークロードは、.NET Framework / .NET Core、Java・Spring Boot、Windows / SMB 依存アプリ、データベースや StatefulSet の永続化、複数 Pod で共有するコンテンツ配信・メディア処理・解析、マルチプロトコル(NFS / SMB / S3)でアクセスする共有データ基盤など。VMware からの移行はその 1 経路として扱います。
- **扱う範囲**: ECS on EC2 の NFS/SMB ホストマウント、EKS on EC2 の NetApp Trident 永続ボリューム(PV)、ECS/EKS on Fargate の S3 Access Points 経由オブジェクトアクセス。
- **キーワード**: FSx for ONTAP, Amazon ECS, Amazon EKS, AWS Fargate, NFS, SMB, NetApp Trident, S3 Access Points, CloudFormation, AWS Transform。
- **現状**: 文献調査 + CloudFormation + 静的検証(cfn-lint)まで。実機デプロイは次段階。
- **一般的な ONTAP 知見**(ブロック PV のボリューム上限、マルチパス、ドライバ選択)は Hub の [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) にあります。本リポジトリはコンテナのデータストア連携に絞ります。

## 移行アプローチ別の位置づけ

既存ワークロードを AWS へ運ぶ経路は 1 つではありません。「どこまでモダナイズするか」で 3 つに分かれ、いずれも着地したデータを FSx for ONTAP に載せられます。新規構築のコンテナで、移行を伴わない場合は下表を飛ばして 5 構成の適合表へ進んでください。

| アプローチ | 何をするか | ツール例 | AWS 上の着地 | コンテナからの到達 | 成熟度 |
|---|---|---|---|---|---|
| リプラットフォーム(コンテナ化) | ソースコードを Docker 化して ECS / EKS へ | AWS Transform containerization | ECS / EKS のコンテナ | Trident PV(NFS / iSCSI)/ ホスト NFS。Fargate 不可 | GA [文書] |
| リホスト(VM のまま EC2) | VM を EC2 へ移し、データを FSx for ONTAP に分離 | AWS Transform for migrations(MGN) | EC2 + FSx for ONTAP | 同一 FSx for ONTAP へ後からコンテナが iSCSI / NFS で共有到達 | GA [文書] |
| サードパーティで VM → EC2 | OS ディスクを EBS、データディスクを FSx for ONTAP へ変換して EC2 へ | NetApp Shift Toolkit v8.0 | EC2 + FSx for ONTAP | 同上。file-to-LUN で file → block 切替も可 | Early Preview(要サポート連絡)[文書] |

**.NET のモダナイズはソースコードから可能** [文書]。AWS Transform は .NET Framework 3.5 / .NET Core 3.1〜.NET 10 を .NET 8 / .NET 10 へ変換し、クロスプラットフォーム化して Linux コンテナにできます(C# / VB.NET(プレビュー)、ASP.NET MVC / Web API / Web Forms など)。WinForms / WPF / Xamarin はプレビュー、Blazor UI や互換ライブラリの無い Win32 DLL は変換対象外(2026-09 時点)。対象の詳細は[派生ドキュメント](docs/ja/atx-containerization-fsxn-derivation.md)を参照してください。

**ONTAP のマルチプロトコル特性が 3 経路に共通する利点** [文書]。同一ボリュームに NFS / SMB / S3 でアクセスでき、プロトコルを切り替えてもデータ移行は要りません。リホスト後に EC2 が使っていたデータへ、コンテナ側が別プロトコルで到達する 2 段階の構成が成り立ちます。Shift Toolkit v8.0 の file-to-LUN(ファイルをブロックへ直接変換)はその具体例で、移行はファイルで高並列に運び、運用は単一ライター前提のブロック性能を取る、といった切り替えに使えます。動機・ユースケースと出典は[派生ドキュメント](docs/ja/atx-containerization-fsxn-derivation.md)の 9 章にあります。

> **成熟度に関する補足**: Shift Toolkit v8.0 の EC2 対応は 2026-09 時点で Early Preview で、EC2 をターゲットにするには NetApp サポートへの連絡が必要です。GA の AWS Transform / MGN とは成熟度が異なるため、設計の前提に据える場合はこの差を明示してください。

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
- [コンテナ移行先での FSx for ONTAP データストア構成の検証](docs/ja/atx-containerization-fsxn-storage-verification.md) — 実機デプロイの前提・順序・落とし穴・後始末は [7.1 デプロイ準備](docs/ja/atx-containerization-fsxn-storage-verification.md#71-デプロイ準備実機検証の前段)
- [ECS on EC2 における FSx for ONTAP のマウント](docs/ja/ecs-ec2-fsxn-mount.md)

## ゲート

```bash
make install   # .venv を固定版で用意
make ci        # cfn-lint + headings + role-labels
```

## 関連リポジトリ

- Hub: [FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) — FSx for ONTAP の設計・構築・運用知見
- [VMware-Migration-EC2-ONTAP](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap) — VMware → EC2 + FSx for ONTAP リホスト移行の検証。SMB 構成が参照する AD はこちらで用意できます
