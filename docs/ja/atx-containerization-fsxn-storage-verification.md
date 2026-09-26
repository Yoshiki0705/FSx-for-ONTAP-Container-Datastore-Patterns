# コンテナ移行先での FSx for ONTAP データストア構成の検証

**目的**: AWS Transform でコンテナ化した後の実行環境(ECS on EC2 / EKS on EC2 / ECS on Fargate / EKS on Fargate)で、Amazon FSx for NetApp ONTAP をデータ領域として使う 4 構成の実現性を一次情報で確定し、実現するものは CloudFormation テンプレート化して静的検証まで行う。

**最終更新**: 2026-09-22
**ステータス**: 文献調査 + CloudFormation 作成 + 静的検証(cfn-lint)まで。実機デプロイは未実施(次段階)

関連: [コンテナ化(ECS/EKS)への派生と FSx for ONTAP の連携可否](atx-containerization-fsxn-derivation.md)。本メモはその調査を受けて「使えるなら、どう構成するか」を CloudFormation に落とす。

---

## 1. 結論

4 構成すべてで FSx for ONTAP をデータ領域に使える。ただし**到達形態が実行環境で分かれる**。EC2 系はファイルマウント(NFS / iSCSI PV)、Fargate 系は S3 オブジェクト API(S3 Access Points)である。

| # | 実行環境 | FSx for ONTAP の到達形態 | アプリ改修 | CloudFormation | 区分 |
|---|---|---|---|---|---|
| 1 | ECS on EC2 | NFS を EC2 ホストにマウント → bind mount | 不要(ファイル I/O のまま) | [作成済み](../../templates/containers-ecs-ec2-fsxn-nfs.yaml) | [文書] |
| 2 | EKS on EC2 | Trident CSI の PV(NFS `ontap-nas` / iSCSI `ontap-san`) | 不要(ファイル I/O のまま) | [作成済み](../../templates/containers-eks-ec2-fsxn-trident.yaml) | [文書] |
| 3 | ECS on Fargate | S3 Access Points 経由の S3 オブジェクト API | 必要(S3 SDK へ) | [作成済み](../../templates/containers-ecs-fargate-fsxn-s3ap.yaml) | [文書] |
| 4 | EKS on Fargate | S3 Access Points 経由の S3 オブジェクト API | 必要(S3 SDK へ) | [作成済み](../../templates/containers-eks-fargate-fsxn-s3ap.yaml) | [文書] |

**要点**: Fargate はボリュームマウントで FSx for ONTAP を使えないが、S3 Access Points 経由の**オブジェクトアクセス**なら使える。ファイル I/O をそのまま維持したいなら EC2 系(1・2)、サーバーレス運用を取るなら Fargate 系(3・4)でアプリを S3 SDK に寄せる、というトレードオフになる。

---

## 2. エビデンス区分

| タグ | 意味 |
|---|---|
| **[実測]** | 本リポジトリで実際に実行して確認済み |
| **[文書]** | AWS / NetApp 公式ドキュメントの記載。出典 URL を併記。実機確認は意味しない |
| **[未確認]** | 実行しておらず公開情報でも裏取りできていない。調査日と調査範囲を併記 |

本メモの CloudFormation は静的検証(cfn-lint)まで [実測] で通しているが、**デプロイして動作することは検証していない** [未確認]。

---

## 3. 構成 1: ECS on EC2 + NFS マウント

### 3.1 実現性 [文書]

ECS から FSx for ONTAP を使う手順は EC2 起動タイプ前提で文書化されている(出典: [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html))。EC2 Linux インスタンスが SVM ボリュームを NFS でマウントし、タスク定義の `volumes`(`host.sourcePath`)と `mountPoints` でコンテナへ bind mount する。Windows は SMB グローバルマッピング。

### 3.2 CloudFormation の設計

- ネットワークは選択式: `CreateNetwork=true` で最小 VPC / サブネットを新規作成、`false` で既存を参照。
- コンテナインスタンスの起動テンプレートで `user-data` が NFS クライアントを導入し、SVM のエンドポイントとジャンクションパスを `/mnt/fsxontap` にマウント、`fstab` に登録する。
- タスク定義は `host.sourcePath: /mnt/fsxontap` を `/data` へ bind mount する。
- FSx for ONTAP の既存セキュリティグループへ、ECS インスタンスからの NFS(2049)ingress を追加する。

**注意**: マウントはインスタンスの起動時処理であり、タスクが作るものではない。マウント前にタスクが起動すると bind mount 先が空になる。マウントは起動の前提条件として扱う。

---

## 4. 構成 2: EKS on EC2 + Trident CSI

### 4.1 実現性 [文書]

AWS の EKS ユーザーガイドが NetApp Trident を FSx for ONTAP 連携の手段として案内している(出典: [Use high-performance app storage with FSx for NetApp ONTAP](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html))。Trident は NFS(`ontap-nas`)と iSCSI(`ontap-san`)の両方の PV を払い出せる(出典: [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html))。

Trident はコントローラ Pod と各ワーカーノードの node pod(DaemonSet)で動くため、**EC2 ワーカーノードが必須**で Fargate では動かない(出典: [Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html))。本構成が managed node group を作るのはこのためである。

### 4.2 CloudFormation の設計と、CloudFormation で作れないもの

- CloudFormation で作れるもの: EKS クラスタ、managed node group、Trident EKS アドオン(`AWS::EKS::Addon`)、IRSA 用 OIDC プロバイダ、ノードのセキュリティグループ。FSx for ONTAP の既存セキュリティグループへ NFS(2049)と iSCSI(3260)の ingress を追加する。
- CloudFormation で作れないもの: PV を生む Kubernetes オブジェクト(TridentBackendConfig / StorageClass / PersistentVolumeClaim)。これらはスタック完了後に kubectl / Helm で適用する。
- Trident EKS アドオンの名称・バージョンは変わりうるため、デプロイ前に `aws eks describe-addon-versions --addon-name netapp_trident-operator` で確認する。

**iSCSI 使用時の注意(対称に記載)**: `ontap-san`(ブロック)を Amazon EBS CSI ドライバと併用する場合、ノードのマルチパス設定が EBS を掴まないよう `multipath.conf` で EBS デバイスを blacklist する必要がある(出典: 上記 EKS ユーザーガイドおよび Trident ドキュメント両方に記載)。

---

## 5. 構成 3・4: Fargate + S3 Access Points

### 5.1 実現性 [文書]

FSx for ONTAP の S3 Access Points は、ボリュームのデータを S3 オブジェクト API(GetObject / PutObject / ListObjectsV2 等)で read/write できる機能である。データは FSx for ONTAP 上に留まり、NFS / SMB と併用できる(出典: [Accessing your data via Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/accessing-data-via-s3-access-points.html))。

**Fargate で成立する理由**: これはボリュームマウントではなく、アプリが SDK で S3 を呼ぶ経路である。Fargate の DaemonSet / 特権 / CSI 制約(構成 2 で問題になったもの)は関与しない。AWS の公式ドキュメントは、Gateway エンドポイントのユースケースとして「VPC 内の Amazon ECS タスク」を含む VPC 内コンピュートを明記している(出典: [Configuring network access for Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html))。Fargate のタスク / Pod は VPC 内の ENI を持つため、この in-VPC コンピュートに該当する。

対応リージョンに東京(ap-northeast-1)が含まれる [文書]。

### 5.2 CloudFormation の設計

- FSx for ONTAP の S3 Access Point は CloudFormation リソース `AWS::FSx::S3AccessPointAttachment` で作成できる(CLI 専用ではない)。ネットワーク origin を VPC にし、ファイルアクセスを認可する UNIX ユーザーを指定する。
- in-VPC からの S3 トラフィックは無料の S3 Gateway VPC エンドポイントを通す。これが `aws:SourceVpc` を付与し、VPC origin のアクセスポイントが要求を受け入れる。
- 認証はコンテナ側の IAM ロール。構成 3(ECS Fargate)はタスクロール、構成 4(EKS Fargate)は IRSA(OIDC プロバイダ + IAM ロール + サービスアカウントの注釈)。

**アクセスポイントポリシーの循環回避**: タスク / IRSA ロールがアクセスポイント ARN を参照し、アクセスポイントポリシーがそのロール ARN を参照すると循環する。同一アカウントでは identity policy とアクセスポイントポリシーのどちらかが許可すれば成立するため、アクセスポイントポリシーの Principal をアカウントルートにし、ロール側の identity policy でアクセスポイントを絞った。VPC origin が VPC 外の要求を deny する。

**IRSA の trust condition(構成 4)**: `<OIDC発行者>:sub` という condition キーは、発行者ホストがクラスタ作成後にしか判明せず、CloudFormation は intrinsic function で condition の**キー**を作れない。そのためテンプレートは Federated principal のみを付与し、`sub` / `aud` のスコープはデプロイ後に trust policy へ手で追加する。共用アカウントでスコープ未設定のまま放置しないこと。

### 5.3 オブジェクト API の制約 [文書]

S3 SDK でアクセスするため、アプリはオブジェクトアクセスに書かれている必要がある。ファイルとしてマウントする用途には使えない。主な制約(出典: [Access point compatibility](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)):

- アップロードの最大オブジェクトサイズは 50 GiB。
- ストレージクラスは FSX_ONTAP のみ、サーバーサイド暗号化は SSE-FSX のみ。
- 非対応: バージョニング、Object Lock、ライフサイクル、条件付き書き込み、Requester Pays、静的 Web ホスティング、`bucket-owner-full-control` 以外の ACL。
- CopyObject / UploadPartCopy は同一アクセスポイント内・同一リージョンのみ。

---

## 6. 4 構成 × ストレージパターンの対応表

| 観点 | 構成 1 ECS/EC2 | 構成 2 EKS/EC2 | 構成 3 ECS/Fargate | 構成 4 EKS/Fargate |
|---|---|---|---|---|
| FSx for ONTAP 到達形態 | NFS host マウント → bind mount | Trident PV(NFS / iSCSI) | S3 Access Points(オブジェクト) | S3 Access Points(オブジェクト) |
| アクセスの粒度 | ファイル(POSIX) | ファイル(NFS)/ ブロック(iSCSI) | オブジェクト | オブジェクト |
| 共有(複数タスク / Pod) | 可(NFS) | NFS は RWX 可 / iSCSI は RWO 中心 | 可(オブジェクト) | 可(オブジェクト) |
| アプリ改修 | 不要 | 不要 | 必要(S3 SDK) | 必要(S3 SDK) |
| 認証 | ホスト経由(IAM 不要) | Secrets Manager / 証明書(Trident) | タスクロール(IAM) | IRSA(IAM) |
| 主なユースケース | 既存ファイル前提の移行 | ステートフル / DB / 共有ファイル | 分析・AI 連携・オブジェクト前提 | 同左 |
| CloudFormation スコープ外 | なし(全部 CFn) | PV 系オブジェクト(kubectl) | なし(全部 CFn) | サービスアカウント注釈 / trust の sub |

---

## 7. 静的検証の結果 [実測 / 2026-09-22]

`make cfn-lint`(cfn-lint、`templates/*.yaml`)が exit 0 で通ることを確認した。4 テンプレートと既存 2 テンプレートを含む。各テンプレートに対応する `params/*.example.json` をダミー値で用意し、キーがテンプレートのパラメータと一致することを確認した(構成 1 の新規ネットワーク用 CIDR パラメータは既定値を持ち、既存参照時は省略されるため未記載)。

**この検証が言っていない範囲**: デプロイして動作することは検証していない。特に以下は実機検証(次段階)で確認する。

| # | 項目 | 調査 / 検証の状態(2026-09-22) |
|---|---|---|
| V1 | 4 構成のデプロイとデータ疎通 | 未実施。cfn-lint のみ [実測] |
| V2 | Trident EKS アドオンの現行名・バージョン | describe-addon-versions で要確認 [未確認] |
| V3 | EKS Pod Identity の Fargate 対応可否 | 本メモは IRSA を採用。Pod Identity の Fargate 対応は未確認 [未確認] |
| V4 | S3 Access Point の UNIX ユーザーと ONTAP 側権限の対応 | 実機で権限設計を確認する必要あり [未確認] |
| V5 | S3 Access Point 経由の実効スループット | 文書は「ファイルシステムのプロビジョンドスループット依存」と記載。実測は未実施 [未確認] |

### 7.1 デプロイ準備(実機検証の前段)

上の V1〜V5 を実機で確認する前に踏む前提・順序・落とし穴・後始末を、やり直しを防ぐ観点でまとめる。実デプロイは課金と共有アカウント変更を伴うため、着手時に個別の承認を取る。

**前提: FSx for ONTAP は本リポジトリのテンプレート外** [実測]。5 テンプレートのいずれも `AWS::FSx::FileSystem` / `StorageVirtualMachine` / `Volume` を作らず、既存の FSx for ONTAP を参照する。デプロイの第 0 段階として、ファイルシステム + SVM + ボリュームを先に用意し、SVM の NFS エンドポイント・ボリュームのジャンクションパス・ファイルシステムのセキュリティグループ ID を控える(構成 1 の `FsxnSvmNfsEndpoint` / `FsxnVolumeJunctionPath` / `FsxnSecurityGroupId` に渡す)。

**確認済みの設計判断(実機で崩さない)**:

- NFS は `nfsvers=4.1` を明示しており、v4.1 は 2049 単一ポートで完結する [実測]。ingress 2049 のみで正しい。111 / 635 / 4045-4049 は NFSv3 用で本構成には不要。
- S3 Access Point ポリシーの循環は、Principal をアカウントルートにしロール側 identity policy で絞ることで回避済み(5.2)。

**着手前に確認する項目(V 番号に対応)**:

| 準備 | 対応する未検証項目 | 確認手段 |
|---|---|---|
| Trident EKS アドオンの現行名・バージョン | V2 | `aws eks describe-addon-versions --addon-name netapp_trident-operator`。ドキュメントは Trident 25.10 系が最新で、本メモの 25.02 参照から進んでいる [文書] |
| S3 Access Point の二層認可(IAM + ファイルシステムレベルの UNIX / Windows ユーザー) | V4 | アクセスポイントに紐づく UNIX ユーザーと ONTAP 側のファイル権限の対応を実機で設計する [文書] |
| 対象リージョンでの提供 | V1 全般 | 第 2 世代 FSx for ONTAP は 2026-04 に 4 リージョン + GovCloud へ拡大。S3 Access Points は東京(ap-northeast-1)対応 [文書]。使うリージョンでの提供を確認する |
| IRSA の trust condition(EKS Fargate) | V3 | `sub` / `aud` はクラスタ作成後に手動で trust policy へ追加(5.2)。共用アカウントで未設定のまま放置しない |

**推奨デプロイ順序**: 最小の構成 1(ECS on EC2 + NFS、CloudFormation 完結・Trident 不要・S3 Access Points 不要)から始める。疎通(タスクから `/data` への読み書き)を確認したら削除し、構成 2(Trident の Kubernetes オブジェクトを kubectl / Helm で適用)、構成 3・4(S3 Access Points、IRSA の手動手順あり)へ段階的に進む。

**落とし穴(実機でやり直しを招く型)**:

- マウントはインスタンスの起動時処理で、タスクが作るものではない。マウント前にタスクが起動すると bind mount 先が空になる(3.2 に既述)。マウントを起動の前提条件として扱う。
- `ontap-san`(iSCSI)を Amazon EBS CSI ドライバと併用する場合、`multipath.conf` で EBS デバイスを blacklist しないとノードのマルチパスが EBS を掴む(4.2 に既述)。
- Trident の StorageClass / PVC / TridentBackendConfig は CloudFormation では作れない。スタック完了後に kubectl / Helm で適用する(4.2 に既述)。

**後始末(検証環境こそ確実に消す)**: 課金が続く主なリソースは FSx for ONTAP ファイルシステム(SSD 容量 + プロビジョンドスループットの時間課金)、EKS クラスタ、EC2 ノード / コンテナインスタンス、NAT / VPC エンドポイント。検証後にスタックを削除し、テンプレート外で先に作った FSx for ONTAP も忘れずに削除する。削除できない検証リソースは長期の請求になり、同居する他のリソースの操作も妨げる。

---

## 8. 分割の判断

実機検証で実現性が確認できた場合、この一連の成果物(4 構成の CloudFormation + アプリ側の改修例)は、EC2 リホストの検証(既存)とは別のリポジトリ / Kiro プロジェクトに分割する余地がある。対象がソースコードとコンテナであり、検証スタック(ECS / EKS / Trident / S3 Access Points)が VMware 移行とは別系統になるためである。分割の是非は実機検証の後に判断する。

---

## 参考リンク

- [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html)
- [Use high-performance app storage with FSx for NetApp ONTAP(EKS User Guide)](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html)
- [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html)
- [Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html)
- [Accessing your data via Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/accessing-data-via-s3-access-points.html)
- [Configuring network access for Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)
- [Access point compatibility](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)
- [AWS::FSx::S3AccessPointAttachment(CloudFormation)](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-fsx-s3accesspointattachment.html) <!-- allow:naming — literal CloudFormation resource type name -->
- [コンテナ化への派生と FSx for ONTAP の連携可否(本リポジトリ)](atx-containerization-fsxn-derivation.md)
