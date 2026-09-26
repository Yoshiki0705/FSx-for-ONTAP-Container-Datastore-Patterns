# コンテナ化(ECS / EKS)への派生と FSx for ONTAP の連携可否

**目的**: AWS Transform のコンテナ化機能(2026-05 発表)で VMware ワークロードを Amazon ECS / Amazon EKS へ移行した場合に、本リポジトリで検証済みの Amazon FSx for NetApp ONTAP 連携が適用できるかを、一次情報で確定する。EC2 リホスト経路との差、Fargate の可否、モダナイズ後にコンテナから FSx for ONTAP を永続ボリューム(PV)/データ領域として使う経路を整理する。

**最終更新**: 2026-09-22
**ステータス**: 文献調査。実機検証は未実施(未検証範囲は各所に [未確認] で明示)

---

## 1. 結論

**コンテナ化して FSx for ONTAP を永続ストレージに使うことは可能だが、それは AWS Transform の機能ではない。** 2 つの機能を分けて理解する必要がある。

| 問い | 回答 | 区分 |
|---|---|---|
| AWS Transform のコンテナ化は ECS / EKS へデプロイできるか | できる。ソースコードを Docker 化し、Amazon ECR へ publish、ECS または EKS へデプロイする | [文書] |
| そのデプロイに Fargate は使えるか | ECS デプロイは Fargate 対応と明記(後述 3.3)。EKS は生成される Helm チャート次第 | [文書] |
| コンテナ化で本リポジトリ検証済みの FSx for ONTAP ブロック連携が付くか | **付かない。** それは AWS Transform for migrations(MGN)の EC2 リホスト専用機能であり、コンテナ化とは別経路 | [文書] |
| AWS Transform のコンテナ化が FSx for ONTAP を PV として構成するか | **しない。** コンテナ化のスコープは Docker 化とデプロイまで。永続ストレージの構成は生成物に含まれない(後述 3.4) | [文書] |
| モダナイズ後の EKS で FSx for ONTAP を PV に使えるか | 使える。ただし AWS Transform ではなく NetApp Trident(CSI ドライバ)を別途導入する。NFS(ファイル)が主、iSCSI(ブロック)も可 | [文書] |
| Fargate で FSx for ONTAP を PV / データ領域に使えるか | **使えない。** EKS Fargate は CSI の node pod(DaemonSet・特権)を動かせず、ECS Fargate は FSx をマウントできない(後述 4) | [文書] |

**設計上の含意**: 「コンテナ化」と「FSx for ONTAP 連携」は 1 つのワークフローにまとまらない。AWS Transform でコンテナ化し、その後 EKS(EC2 ワーカーノード)へ Trident を導入して PV を構成する、という 2 段階になる。Fargate を選ぶと FSx for ONTAP は選べない。この 2 つはトレードオフの関係にある。

---

## 2. エビデンス区分

| タグ | 意味 |
|---|---|
| **[実測]** | 本リポジトリで実際に実行して確認済み(出典は既存の検証レポート) |
| **[文書]** | AWS / NetApp 公式ドキュメントの記載。出典 URL を併記。実機確認は意味しない |
| **[未確認]** | 実行しておらず、公開情報でも裏取りできていない。調査日と調査範囲を併記 |

「公開ドキュメントに記載が見つからない」ことは製品の挙動ではなくドキュメントの状態についての事実である。[未確認] には**いつ・どこを探したか**を添える。

---

## 3. 2 つの AWS Transform 機能の切り分け

### 3.1 コンテナ化機能の範囲 [文書]

AWS Transform のコンテナ化は、**ソースコードを入力**にコンテナ化する機能である(2026-05-11 発表、出典: [What's New](https://aws.amazon.com/about-aws/whats-new/2026/05/aws-transform-containerization/) / [Source code containerization](https://docs.aws.amazon.com/transform/latest/userguide/transform-containers.html))。

| 項目 | 内容 |
|---|---|
| 入力 | GitHub / Bitbucket / GitLab(AWS CodeConnections 経由)または .zip。個別ファイル 1 GB 以下、総計 8 GB 以下 |
| 処理 | ソースコード解析 → Dockerfile 生成 → コンテナイメージのビルドと CVE スキャン → ECR へ publish |
| 出力(IaC) | EKS 向けは Helm チャート、ECS 向けは Terraform モジュール。検証つきで生成 |
| 依存解決 | AWS CodeArtifact(Maven / PyPI / npm)と private ECR ベースイメージを依存元に指定可 |
| 対応構成 | monorepo / multi-repo。数千アプリのスケール対応と記載 |
| デプロイ先 | Amazon ECS または Amazon EKS |

**明記された除外**: コンテナ化は「まだコンテナ化されていないアプリケーション向け」であり、**既にコンテナ化済みのワークロードの移行は対象外**。既存コンテナは ECS / EKS の標準デプロイ手法を使う、と公式ドキュメントに明記されている。

コンテナ化は VMware migration ジョブ内で、単独ワークフロー(standalone)としても、移行ウェーブの戦略を `containerize` に設定した end-to-end 移行の一部としても実行できる。

### 3.2 対応するソースワークロード種別 [文書]

コンテナ化はソースコードを解析するため、対応言語・フレームワークがソースワークロードの範囲を決める。.NET のモダナイズについては範囲が明記されている(出典: [Modernizing .NET with AWS Transform](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html))。

| 項目 | 内容 |
|---|---|
| 変換元 | .NET Framework 3.5、.NET Core 3.1、.NET 5.x〜.NET 10 |
| 変換先 | .NET 8、.NET 10、.NET Standard(クラスライブラリ) |
| 言語 | C#、VB.NET(プレビュー) |
| プロジェクト種別 | クラスライブラリ、コンソールアプリ、ASP.NET(MVC / Web API / Web Forms)、単体テスト(NUnit / xUnit / MSTest)、WCF サービス |
| プレビュー種別 | デスクトップ(WinForms / WPF)、モバイル(Xamarin)、ASMX Web サービス |
| 変換不可 | Blazor UI コンポーネント、コア互換ライブラリの無い Win32 DLL、.NET ソリューションを含まないリポジトリ、プロジェクトファイルの無い Web サイト |

.NET エージェントは .NET-to-.NET 変換に限られる。非 .NET(例: Web Forms → React)は AWS Transform custom を使う、と記載がある。コンテナ化自体はソースコード解析であり .NET に限定されないが、**本調査時点(2026-09-22)で対応言語の網羅的な一覧を公式ドキュメントに確認できていない [未確認]**(確認先: 上記コンテナ化ユーザーガイドと .NET ユーザーガイド)。

### 3.3 デプロイ先と Fargate の可否 [文書]

AWS Transform がコンテナ化アプリを ECS へデプロイするための AWS マネージドポリシー `AWSTransformApplicationECSDeploymentPolicy` の説明には、「AWS Transform が **Fargate を使用して** Amazon ECS にアプリケーションをデプロイできるようにする」と明記されている(出典: [AWSTransformApplicationECSDeploymentPolicy](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AWSTransformApplicationECSDeploymentPolicy.html))。

このポリシーが付与する権限は、ECS のクラスタ / サービス / タスク定義、ECR、CloudWatch Logs、および `iam:PassRole`(ECS タスクロール / 実行ロール)に限られる。**EBS / EFS / FSx for ONTAP のいずれについても、ボリューム系の権限は含まれない。** つまり AWS Transform が生成する ECS デプロイは、Fargate 上でステートレスに動くことを前提とした構成であり、永続ストレージのプロビジョニングはこのポリシーの範囲外である。

### 3.4 コンテナ化のスコープに含まれないもの [文書 + 未確認]

コンテナ化のワークフローは 9 段階(セキュリティ免責の確認 → ソース取得 → コンテナ化 → 生成物レビュー → イメージ publish → IaC 生成 → テスト環境デプロイ → テスト環境撤去 → 本番デプロイ)で、いずれの段階にも永続ボリューム / データストアの構成は含まれない。

**AWS Transform のコンテナ化生成物(Helm チャート / Terraform モジュール)が FSx for ONTAP の PV / PVC / StorageClass を出力するという記載は、本調査時点(2026-09-22)で見つからなかった [未確認]**(確認先: コンテナ化ユーザーガイド、ECS デプロイ用マネージドポリシー)。永続ストレージはコンテナ化とは別に、デプロイ先クラスタ側で構成するという理解が妥当である。

### 3.5 追加の疑問への回答(入力の種類とマウント構成) [文書 + 未確認]

以下は 2 点の具体的な問いに一次情報で答える。出典は launch ブログ [Containerize during migration](https://aws.amazon.com/blogs/migration-and-modernization/containerize-during-migration-replatform-applications-to-containers-with-aws-transform/) と 3.1〜3.4 の各ドキュメント。

**Q1: ソースコード以外(VMware VM や実行中の Windows/.NET ワークロード)を入力にコンテナ化できるか。**

できない。入力は常に**ソースコード**(CodeConnections 経由の Git リポジトリまたは zip)である [文書]。VMware VM や実行中サーバーを直接コンテナ化する経路は、AWS Transform のコンテナ化には無い。

- end-to-end 移行では、**リホスト(EC2)と コンテナ化(ソースコード)が並行する 2 トラック**として実行される。同一プロジェクトで「rehost する VM」と「replatform するソースコード」を横並びに扱うが、VMware VM がコンテナ化トラックに入るわけではない [文書]。
- Windows / .NET のワークロードも、コンテナ化に渡すのはソースコードである。.NET Framework の場合は 3.2 の範囲でクロスプラットフォーム .NET へ移行したうえでコンテナ化する流れになる。**実行中サーバーやバイナリからのコンテナ化(ソースコード不要の経路)は AWS Transform のコンテナ化ではなく、別ツールである AWS App2Container の領域**で、App2Container は「アプリのコンテナ化にソースコードを必要としない」と明記している [文書](出典: [What is AWS App2Container?](https://docs.aws.amazon.com/app2container/latest/UserGuide/what-is-a2c.html))。両者は入力が異なる別機能である。

**Q2: ECS 化時に NFS/SMB マウントポイントを、EKS 化時に FSx for ONTAP を PV として指定できるか(生成物の中で)。**

**本調査時点(2026-09-22)で、AWS Transform が自動生成する成果物にその構成は確認できなかった [未確認]。** launch ブログが例示する ECS 生成物は、ECS クラスタ(Fargate)+ Application Load Balancer + Secrets Manager プレースホルダ + CloudWatch ロググループであり、NFS/SMB マウントポイントや永続ボリュームは含まれていない。EKS 生成物は Helm チャートで、**既存の EKS クラスタを要求する**とされ、PV/StorageClass の自動生成には言及がない。

したがって、NFS/SMB マウント(ECS)や FSx for ONTAP を PV に指定(EKS)する構成は、コンテナ化の生成物の外側で、デプロイ先クラスタ側に別途組み込む必要がある(4 章)。生成物はチャットで調整できると記載があるため、テンプレートを人手で拡張する余地はあるが、**「FSx for ONTAP を PV に指定する既定の生成物がある」わけではない**。

---

## 4. FSx for ONTAP とコンテナ実行環境の連携

「コンテナ化した後」に FSx for ONTAP を使う経路は、デプロイ先ごとに手段と制約が異なる。

### 4.1 EKS における連携(NetApp Trident) [文書]

AWS の EKS ユーザーガイドは、EKS から FSx for ONTAP を永続ストレージとして使う手段として **NetApp Trident**(CSI 準拠ドライバ)を公式に案内している(出典: [Use high-performance app storage with FSx for NetApp ONTAP](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html))。AWS 独自の FSx for ONTAP 用 CSI ドライバは別に存在せず、この CSI ドライバが Trident を指す。AWS が EKS との連携を検証した Trident EKS アドオンも提供されている(出典: [Configure the Trident EKS add-on](https://docs.netapp.com/us-en/trident/trident-use/trident-aws-addon.html))。

Trident は EKS クラスタに対して**ブロックとファイルの両方の PV** を FSx for ONTAP から払い出せる(出典: [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html))。

| ドライバ | プロトコル | ボリュームモード | アクセスモード | 主な用途 |
|---|---|---|---|---|
| `ontap-nas` | NFS(v3 / v4.1)、SMB | ファイル | RWX 可(共有) | 複数 Pod が同一 PVC を共有するワークロード |
| `ontap-san` | iSCSI | ブロック | ブロックモードで RWO / ROX / RWX / RWOP、ファイルモードで RWO / RWOP | 単一ライターの永続化、専用ディスク |

出典: [ONTAP SAN driver overview](https://docs.netapp.com/us-en/trident/trident-use/ontap-san.html)。NetApp の統合ガイドは「複数 Pod が同一 PVC を共有するなら NAS ドライバ、非共有なら iSCSI ブロックドライバ」を既定の選択としている(出典: [Integrate Trident](https://docs.netapp.com/us-en/trident/trident-reco/integrate-trident.html))。

**運用上の注意(対称に記載)**:

- iSCSI(`ontap-san`)を使う場合、ノードのマルチパス設定が Amazon EBS CSI ドライバと競合しうる。`multipath.conf` で EBS デバイスを blacklist する必要がある(出典: 上記 EKS ユーザーガイドおよび Trident ドキュメント両方に記載)。
- SMB ボリュームは `ontap-nas` ドライバのみ、Windows ノードのみで、Trident EKS アドオンでは非対応。
- NVMe-oF は Trident 25.02 のテスト対象に含まれていない [文書]。

**一般 ONTAP 知見は Hub 参照**: 以下 3 点はコンテナ横断で共通するため本リポジトリでは複製せず、Hub([FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook))の block-storage domain に委ねる。

- ブロック PV のボリューム上限: [Kubernetes のブロックボリュームとボリューム上限](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/kubernetes-block-volumes-and-the-volume-limit.md)
- マルチパス(フェイルオーバー): [パスがフェイルオーバーの機構](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/paths-are-the-failover-mechanism.md)
- ドライバ / プロトコル選択: [プロトコル選択は選ぶ前に定まっている](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/protocol-choice-is-bounded-before-you-choose.md)

### 4.2 ECS における連携(EC2 起動タイプ) [文書]

ECS から FSx for ONTAP を使う手順は、**EC2 起動タイプ**を前提に文書化されている(出典: [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html))。

- Linux コンテナ: EC2 Linux インスタンスに NFS でボリュームをマウントし、タスク定義の `volumes`(`host.sourcePath`)と `mountPoints` でコンテナへ bind mount する。
- Windows コンテナ: ドメイン参加した EC2 Windows インスタンスで SMB グローバルマッピングを作成し、同様にタスク定義で bind mount する。

いずれもコンテナランタイムが直接 FSx をマウントするのではなく、**ホストの EC2 インスタンスがマウントしたものを bind mount する**構造である。関連して、ECS と FSx for Windows File Server の組み合わせは Windows EC2 のみ対応で、Linux EC2 と Fargate は対象外である(出典: [Use FSx for Windows File Server volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/wfsx-volumes.html))。

### 4.3 Fargate の制約 [文書]

**Fargate では FSx for ONTAP を PV / データ領域として使えない。** ECS / EKS のどちらの Fargate でも制約が異なる理由で成立しない。

| 実行環境 | 制約 | 出典 |
|---|---|---|
| EKS Fargate | DaemonSet、特権(Privileged)Pod、HostNetwork / HostPort が使えない。Trident は各ワーカーノードで node pod(DaemonSet)を動かす設計のため、Fargate では起動できない | [Simplify compute management with AWS Fargate](https://docs.aws.amazon.com/eks/latest/userguide/fargate.html)、[Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html) |
| EKS Fargate(他ストレージ) | EFS CSI は Fargate で動的プロビジョニング不可・静的のみ。EBS CSI は controller は Fargate 可だが node DaemonSet は EC2 のみ。Fargate で使える永続は EFS(静的)に限られる | [Amazon EFS CSI driver](https://docs.aws.amazon.com/eks/latest/userguide/efs-csi.html)、[Amazon EBS CSI driver](https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html) |
| ECS Fargate | タスク定義は bind mount host ボリュームと EFS ボリュームのみ対応。`dockerVolumeConfiguration` 非対応。FSx for ONTAP はサポートされるボリューム種別に含まれない | [Amazon ECS task definition differences for Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html) |

したがって「AWS Transform の ECS デプロイは Fargate 対応(3.3)」と「Fargate では FSx for ONTAP を使えない(本節)」は両立する。**Fargate の運用簡素化を取るなら FSx for ONTAP は付けられず、FSx for ONTAP の永続ボリュームを取るなら EKS の EC2 ワーカーノード(または ECS の EC2 起動タイプ)を選ぶ**、というトレードオフになる。

---

## 5. ブロックストレージのユースケース

FSx for ONTAP のブロック(iSCSI LUN)利用について、想定どおりデータベースのデータ置き場が代表的だが、それに限らない。ブロック(RWO 中心)とファイル(RWX 可)は用途が分かれる。

| パターン | 代表的なユースケース | 根拠 |
|---|---|---|
| ブロック / iSCSI(RWO) | データベースのデータ領域、単一ライターの永続化、専用 IOPS を要求するワークロード、raw ブロックデバイスを前提とするミドルウェア、StatefulSet の各レプリカ専用ボリューム | 「非共有ストレージは block / iSCSI ドライバ」([Integrate Trident](https://docs.netapp.com/us-en/trident/trident-reco/integrate-trident.html))。ブロックストレージは一般に RWO で単一ノード書き込み向き |
| ファイル / NFS(RWX) | 複数 Pod で共有するコンテンツ管理、メディア処理、Web 配信、水平スケールするアプリの共有データ | 「共有ストレージ(複数 Pod が同一 PVC)は NAS ドライバ」(同上)。EC2 リホストではなくコンテナ化後に共有領域が要る場合に該当 |

**EC2 リホスト経路との違い**: MGN 経由の EC2 リホストでは、データディスクは FlexVol 内の LUN として配置され、ゲスト OS からは iSCSI(DM-Multipath / ALUA)で見える(出典: [AWS Transform の FSx for ONTAP 対応 GA 検証(別リポジトリ)](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/ja/atx-fsxn-ga-verification.md))。これはコンテナ環境の PV とは別の到達形態である。コンテナ環境では PV/PVC/StorageClass の抽象を通して Trident が LUN またはボリュームを払い出す。EC2 リホスト経路の検証は別リポジトリ [VMware-Migration-EC2-ONTAP](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap) にある。

---

## 6. ワークロード種別 × 移行先 × ストレージパターンの適合表

行はソースワークロードの性質、列は移行先の実行環境、セルは FSx for ONTAP をどのストレージパターンで使えるか。すべて公開ドキュメントに基づく [文書]。実機での再現は本リポジトリでは EC2 リホストのみ [実測] で、コンテナ経路は [未確認]。

凡例: **NFS PV** = Trident `ontap-nas` / **iSCSI PV** = Trident `ontap-san` / **iSCSI(ゲスト)** = ゲスト OS 内の iSCSI マウント / **host NFS/SMB** = ECS の EC2 ホスト経由 bind mount / **✕** = FSx for ONTAP 連携なし

| ソースワークロード | EC2 リホスト(MGN) | EKS(EC2 ワーカー) | EKS Fargate | ECS(EC2 起動) | ECS Fargate |
|---|---|---|---|---|---|
| データベース(専用ディスク要求) | iSCSI(ゲスト)[実測] | iSCSI PV / NFS PV [文書] | ✕(CSI 不可)[文書] | host NFS [文書] | ✕(接続不可)[文書] |
| ステートフルな .NET / Java アプリ(単一ライター) | iSCSI(ゲスト)[文書] | iSCSI PV [文書] | ✕ [文書] | host NFS [文書] | ✕ [文書] |
| 共有データを持つ水平スケール Web アプリ | iSCSI(ゲスト)[文書] | NFS PV(RWX)[文書] | ✕ [文書] | host NFS [文書] | ✕(EFS のみ)[文書] |
| ステートレス Web / API | 該当薄(データ無) | 任意(不要なら未使用) | 永続不要 [文書] | 任意 | Fargate 適(永続不要)[文書] |
| Windows / SMB 依存アプリ | iSCSI(ゲスト)[文書] | SMB PV(Windows ノード)[文書] | ✕ [文書] | host SMB(Windows EC2)[文書] | ✕ [文書] |

**表の読み方**:

- **EC2 リホスト列**が、本リポジトリで検証済みの経路(AWS Transform for migrations の FSx for ONTAP ブロックサポート)。コンテナ化とは別機能で、リホストのみに適用される。
- **Fargate の 2 列**はいずれも FSx for ONTAP と接続できない。ステートレスなワークロードであれば Fargate が適し、FSx for ONTAP は不要。永続領域に FSx for ONTAP を要求するワークロードは、Fargate ではなく EC2 ワーカー / EC2 起動タイプを選ぶ。
- **コンテナ列の FSx for ONTAP 連携はすべて Trident 等の別途導入が前提**で、AWS Transform のコンテナ化が自動構成するものではない。

---

## 7. 実現するための段階と分割の判断

D フェーズ(本リポジトリでは文献調査)の結論として、コンテナ経路の FSx for ONTAP 連携を実機検証する場合の段階を示す。実機検証は本セッションでは未実施。

1. **コンテナ化**: AWS Transform でソースコードをコンテナ化し、ECR へ publish、EKS(EC2 ワーカーノード)へデプロイ。
2. **CSI 導入**: EKS クラスタに NetApp Trident を導入(Helm または AWS 検証済み EKS アドオン)。FSx for ONTAP のファイルシステムと SVM、認証情報(Secrets Manager)を用意。
3. **PV 構成**: 用途に応じて `ontap-nas`(NFS / 共有)または `ontap-san`(iSCSI / 専用)の StorageClass を作り、アプリの PVC から要求する。
4. **検証**: データ整合性、フェイルオーバー時の挙動、iSCSI 使用時の EBS multipath 競合の回避を確認。

この経路は EC2 リホストの検証(既存)とは別のリポジトリ / Kiro プロジェクトに分割する余地がある。理由は、(a) 対象が VMware VM ではなくソースコードであること、(b) 検証に EKS クラスタと Trident という別のスタックが要ること、(c) FSx for ONTAP の到達形態が iSCSI ゲストマウントから CSI PV へ変わること。分割の是非は、実機検証で実現性を確認してから判断する。

---

## 8. 未確認事項

| # | 項目 | 調査した範囲(2026-09-22) |
|---|---|---|
| C1 | コンテナ化の対応言語の網羅的一覧 | コンテナ化ユーザーガイドと .NET ユーザーガイドを確認。.NET の範囲は明記されているが、コンテナ化全体の対応言語一覧は見つからず |
| C2 | AWS Transform 生成 IaC が FSx for ONTAP PV / NFS・SMB マウントを出力するか | コンテナ化ユーザーガイド、ECS デプロイ用マネージドポリシー、launch ブログの生成物例(ECS = クラスタ + ALB + Secrets Manager + CloudWatch)を確認。永続ストレージ / マウント構成の記載なし。出力しないという理解(3.5) |
| C3 | コンテナ経路の FSx for ONTAP 連携の実機挙動 | 本セッションでは未実施。EC2 リホストのみ既存レポートで [実測] |
| C4 | Trident の Fargate 非対応の公式明記 | Trident が node pod(DaemonSet)を要すること、Fargate が DaemonSet / 特権を不可とすることは各々出典あり。「Trident は Fargate 非対応」と 1 文で述べた公式記載そのものは未確認 |

---

## 9. サードパーティツールによる VM → EC2 移行(NetApp Shift Toolkit v8.0)

ここまでの 1〜8 章は AWS Transform を軸にした経路である。VMware VM を AWS 上に運び、その
データ領域を FSx for ONTAP に載せる経路は、AWS Transform / MGN のほかに **NetApp Shift
Toolkit** でも成立する。本リポジトリの主題(コンテナのデータストア)に対しては、これは
「移行の入口」を提供し、着地した FSx for ONTAP へ後からコンテナが到達する 2 段階の前段に
あたる。

### 9.1 Shift Toolkit の位置づけ [文書]

Shift Toolkit はハイパーバイザ間の VM 移行とディスク変換を行うスタンドアロン製品で、
FlexClone による高速変換を特徴とする(出典: [Shift Toolkit overview](https://docs.netapp.com/us-en/netapp-solutions/vm-migrate/migrate-overview.html))。
従来の変換先は VMware ESXi ⇄ Microsoft Hyper-V、ESXi → OLVM / Red Hat OpenShift
Virtualization / Proxmox VE で、**この overview の版には AWS / EC2 が着地先として現れない**。
AWS 対応は次の v8.0 で preview 機能として加わった。

### 9.2 v8.0 の AWS 対応(Early Preview)[文書][Preview]

Shift Toolkit v8.0 は preview 機能として AWS への移行を導入した(出典: [What's New in Shift v8.0(NetApp Community)](https://community.netapp.com/community/discussion/467669/what-s-new-in-shift-v8-0-file-to-lun-ec2-fsx-for-ontap-trident-integration-more))。

| 機能 | 内容 | 成熟度 |
|---|---|---|
| EC2 with FSx for ONTAP Support | VM の **OS ディスクを EBS 形式**へ、**データディスクを FSx for ONTAP** へ変換して EC2 へ移行。ONTAP snapshot / SnapMirror / FSx for ONTAP を用い、従来のコピー処理を排する。OS ディスク変換は AWS Import/Export API と Direct Access API(EBS snapshot 作成)の 2 経路 | Early Preview |
| File-to-LUN migration | FlexVol 上の既存ファイル(VMDK 等)を **block(iSCSI LUN)へ直接変換**。データレイアウトを保持 | Preview |
| Shift as an Add-On for Trident | Trident 26.06 以降で、OpenShift Virtualization 向けに CSI プロビジョナと統合。zero-copy cold migration | Preview |

**Early Preview の制約(明示が必要)**: EC2 をターゲットとして有効化するには、本調査時点
(2026-09-23)で NetApp サポート窓口への連絡が必要と記事に明記されている。GA の AWS Transform /
MGN とは成熟度が異なるため、設計の前提に据える場合はこの差を明記する。

#### file → block(iSCSI LUN)へ切り替えたい理由

記事は file-to-LUN を「ファイルベースからブロック(iSCSI LUN)へシームレスに移行し、データ
レイアウトを保持する」機能と説明する [文書]。記事が挙げる動機は移行の速度と並列性である。
ブロックストレージ backed のハイパーバイザから直接コピーや VDDK 経由で運ぶと時間がかかる
ため、いったん ONTAP の NFS データストアへ storage vMotion し、そこから**高い並列度で**
移行先(記事の例は OpenShift Virtualization)のブロックへ変換する、という流れが示されている
[文書]。移行の入口をファイルにすると速く柔軟に運べ、着地をブロックにすると次の運用要件に
合わせられる、という切り替えである。

以下は記事が個別に列挙しているわけではなく、ONTAP のブロック / ファイル用途区分(5 章)から
導ける一般的な動機である [文書, 一般論]。

- **移行はファイル、運用はブロック**: 移行フェーズは NFS(ファイル)で高並列・低運用コストに
  運び、運用フェーズは iSCSI LUN(ブロック)で単一ライター前提の性能や専用ディスクを取る。
- **ブロックを要求するワークロード**: データベースのデータ領域、raw ブロックデバイスを前提と
  するミドルウェア、StatefulSet 各レプリカの専用ボリューム、専用 IOPS を要求する処理。いずれも
  ファイル共有(RWX)ではなくブロック(RWO 中心)が適する(5 章の区分と整合)。
- **VM ディスクをブロックとして扱う移行先**: OpenShift Virtualization / KubeVirt は VM ディスク
  をブロック PVC で扱うのが一般的で、ファイルとして運んだディスクをブロック LUN へ変換して
  着地させる需要がある。

ユースケースは特定顧客の事例ではなく類型として示す。file-to-LUN は Preview 機能のため、実機
挙動と適合するワークロードの確定は実機検証を要する(9.4 の C5 / C6)。

### 9.3 コンテナのデータストアとの接続(2 段階移行)[文書]

Shift Toolkit v8.0 で VM を EC2 + FSx for ONTAP へ運ぶと、データは FSx for ONTAP の
ボリューム / LUN に載る。この同一データに、後からコンテナ側(EKS の Trident PV、ECS の
EC2 ホスト経由 NFS)が **iSCSI または NFS** で到達できる。ONTAP のマルチプロトコル特性により、
同一ボリュームへ複数プロトコルでアクセスでき、プロトコル切替時のデータ移行を要しない
(1〜8 章の Trident / host NFS 経路がそのまま適用される)。v8.0 の file-to-LUN 機能は、
ファイルとして移行したものをブロックへ切り替える具体例にあたる。

到達形態と Fargate の制約(4 章)は移行の入口が AWS Transform か Shift Toolkit かに依らず
同じである。すなわち Fargate では FSx for ONTAP を PV / データ領域に使えず、EC2 ワーカー /
EC2 起動タイプを選ぶ、というトレードオフはこの経路でも変わらない。

### 9.4 未確認事項(9 章)

| # | 項目 | 調査した範囲(2026-09-23) |
|---|---|---|
| C5 | v8.0 AWS 対応の GA 時期と一般提供条件 | community 記事で Early Preview と確認。GA 時期・サポート連絡なしで使える条件は記事に記載なし |
| C6 | EC2 移行後のデータディスク(FSx for ONTAP)へのコンテナ到達の実機挙動 | 本リポジトリでは未実施。ONTAP マルチプロトコルと Trident の一般特性からの推定 |

---

## 参考リンク

- [AWS Transform adds containerization capability during migrations(What's New, 2026-05-11)](https://aws.amazon.com/about-aws/whats-new/2026/05/aws-transform-containerization/)
- [Source code containerization(AWS Transform User Guide)](https://docs.aws.amazon.com/transform/latest/userguide/transform-containers.html)
- [Containerize during migration: Replatform applications to containers with AWS Transform(AWS Blog)](https://aws.amazon.com/blogs/migration-and-modernization/containerize-during-migration-replatform-applications-to-containers-with-aws-transform/)
- [What is AWS App2Container?](https://docs.aws.amazon.com/app2container/latest/UserGuide/what-is-a2c.html)
- [Modernizing .NET with AWS Transform](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html)
- [AWSTransformApplicationECSDeploymentPolicy(AWS Managed Policy)](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AWSTransformApplicationECSDeploymentPolicy.html)
- [Use high-performance app storage with FSx for NetApp ONTAP(EKS User Guide)](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html)
- [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html)
- [ONTAP SAN driver overview(Trident)](https://docs.netapp.com/us-en/trident/trident-use/ontap-san.html)
- [Integrate Trident](https://docs.netapp.com/us-en/trident/trident-reco/integrate-trident.html)
- [Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html)
- [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html)
- [Amazon ECS task definition differences for Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html)
- [Simplify compute management with AWS Fargate(EKS)](https://docs.aws.amazon.com/eks/latest/userguide/fargate.html)
- [AWS Transform の FSx for ONTAP 対応 GA 検証(別リポジトリ VMware-Migration-EC2-ONTAP)](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/ja/atx-fsxn-ga-verification.md)
- [手順: AWS Transform による VMware → EC2 / FSx for ONTAP 移行(別リポジトリ)](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/ja/aws-transform-migration-procedure.md)
- [NetApp Shift Toolkit overview(ハイパーバイザ間移行)](https://docs.netapp.com/us-en/netapp-solutions/vm-migrate/migrate-overview.html)
- [What's New in Shift v8.0: File-to-LUN, EC2 + FSx for ONTAP, Trident(NetApp Community)](https://community.netapp.com/community/discussion/467669/what-s-new-in-shift-v8-0-file-to-lun-ec2-fsx-for-ontap-trident-integration-more)
