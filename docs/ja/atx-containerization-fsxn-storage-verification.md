# コンテナ移行先での FSx for ONTAP データストア構成の検証

**目的**: AWS Transform でコンテナ化した後の実行環境(ECS on EC2 / EKS on EC2 / ECS on Fargate / EKS on Fargate)で、Amazon FSx for NetApp ONTAP をデータ領域として使う 4 構成の実現性を一次情報で確定し、実現するものは CloudFormation テンプレート化して静的検証まで行う。

**最終更新**: 2026-10-29
**ステータス**: 文献調査 + CloudFormation 作成 + 静的検証(cfn-lint)+ 構成 1・2 の実機デプロイ(小規模、3.3 と 4.3)。構成 3・4 の実機デプロイは未実施(次段階)

関連: [コンテナ化(ECS/EKS)への派生と FSx for ONTAP の連携可否](atx-containerization-fsxn-derivation.md)。本メモはその調査を受けて「使えるなら、どう構成するか」を CloudFormation に落とす。

---

## 1. 結論

4 構成すべてで FSx for ONTAP をデータ領域に使える。ただし**到達形態が実行環境で分かれる**。EC2 系はファイルマウント(NFS / iSCSI PV)、Fargate 系は S3 オブジェクト API(S3 Access Points)である。

| # | 実行環境 | FSx for ONTAP の到達形態 | アプリ改修 | CloudFormation | 区分 |
|---|---|---|---|---|---|
| 1 | ECS on EC2 | NFS を EC2 ホストにマウント → bind mount | 不要(ファイル I/O のまま) | [作成済み](../../templates/containers-ecs-ec2-fsxn-nfs.yaml) | [文書]・[実測](3.3) |
| 2 | EKS on EC2 | Trident CSI の PV(NFS `ontap-nas` / iSCSI `ontap-san`) | 不要(ファイル I/O のまま) | [作成済み](../../templates/containers-eks-ec2-fsxn-trident.yaml) | [文書]・[実測](4.3) |
| 3 | ECS on Fargate | S3 Access Points 経由の S3 オブジェクト API | 必要(S3 SDK へ) | [作成済み](../../templates/containers-ecs-fargate-fsxn-s3ap.yaml) | [文書] |
| 4 | EKS on Fargate | S3 Access Points 経由の S3 オブジェクト API | 必要(S3 SDK へ) | [作成済み](../../templates/containers-eks-fargate-fsxn-s3ap.yaml) | [文書] |

**要点**: Fargate はボリュームマウントで FSx for ONTAP を使えないが、S3 Access Points 経由の**オブジェクトアクセス**なら使える。ファイル I/O をそのまま維持したいなら EC2 系(1・2)、サーバーレス運用を取るなら Fargate 系(3・4)でアプリを S3 SDK に寄せる、というトレードオフになる。

---

## 2. エビデンス区分

| タグ | 意味 |
|---|---|
| **[実測]** | 本リポジトリで実機で実行して確認済み |
| **[文書]** | AWS / NetApp のドキュメント上の記載、実機では未確認。出典 URL を併記 |
| **[未測定]** | 実行していない、またはこの範囲では扱っていない。調査日と調査範囲を併記 |

本メモの CloudFormation は静的検証(cfn-lint)まで [実測] で通している。デプロイして動作することは、構成 1(3.3)と構成 2(4.3)について小規模に確認した。**構成 3・4 は、デプロイして動作することを検証していない** [未測定]。

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

### 3.3 構成 1 の実機確認結果

**範囲**: 2026-11-10、ap-northeast-1、既存の Single-AZ の FSx for ONTAP 上に作った使い捨ての SVM とボリューム(UNIX スタイル、1 GiB、ジャンクションパス `/ecsvol`)、各項目 1 回の観測、スタックの存続は約 25 分。テンプレートは origin/main の 09c079b のものを無改造で使った。小規模の確認であり、性能、Multi-AZ のフェイルオーバー、複数タスクが同じファイルへ同時に書くときの整合、Windows(SMB、構成 1b)は含まない。

| 項目 | 結果 [実測] |
|---|---|
| スタックの作成 | ECS サービスが定常状態に達せず、そのままでは `CREATE_COMPLETE` にならなかった。原因はマウントではなく、プレースホルダのイメージ(`amazonlinux`)が引数なしで即座に終了(exit 0)し、サービスがタスクを起動し直し続けたこと。サービスの希望数を 0 にするとスタックが完了した。テンプレートには `ContainerCommand` パラメータ(既定 `sleep infinity`、空文字で自前イメージの CMD を使う)を足した。この変更は cfn-lint のみで、デプロイして確かめていない |
| ホストのマウント(インスタンス 2 台) | 両方で `/mnt/fsxontap` が NFS v4.1 でマウントされていた。ingress は 2049 のみ(111 などは開けていない) |
| 別インスタンスのタスク間の共有 | インスタンス 1 のタスクが `/data` に書いたマーカーを、インスタンス 2 のタスクが読めて一致した |
| タスクの入れ替え | 書き込んだタスクを停止し、新しいタスクを起動して読むと一致した |
| インスタンスの置き換え | インスタンス 1 を終了し、Auto Scaling が起動した新しいインスタンスにタスクを置くと、起動時のマウントが成立し、マーカーが一致した |

確認には、タスク定義はそのままに `start-task` のコマンド上書き(`sh -c`)でマーカーを書き読みし、CloudWatch Logs で出力を読んだ。ECS Exec は使っていない(テンプレートにタスクロールが無い)。撤去後は、SVM、ボリューム、バックアップ、FSx のセキュリティグループの ingress、ネットワークインターフェイス数(72)がベースラインと一致した。

**観測の範囲**: NFS の export policy は、FSx for ONTAP の新しい SVM の既定のまま変更しなかった。クライアントの CIDR を絞る設計は確かめていない。

---

## 4. 構成 2: EKS on EC2 + Trident CSI

### 4.1 実現性 [文書]

AWS の EKS ユーザーガイドが NetApp Trident を FSx for ONTAP 連携の手段として案内している(出典: [Use high-performance app storage with FSx for NetApp ONTAP](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html))。Trident は NFS(`ontap-nas`)と iSCSI(`ontap-san`)の両方の PV を払い出せる(出典: [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html))。

Trident はコントローラ Pod と各ワーカーノードの node pod(DaemonSet)で動くため、**EC2 ワーカーノードが必須**で Fargate では動かない(出典: [Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html))。本構成が managed node group を作るのはこのためである。

### 4.2 CloudFormation の設計と、CloudFormation で作れないもの

- CloudFormation で作れるもの: EKS クラスタ、managed node group、Trident EKS アドオン(`AWS::EKS::Addon`)、IRSA 用 OIDC プロバイダ、`PrepareNodesForIscsi=true` のときの iSCSI 用ノード準備(launch template)。FSx for ONTAP の既存セキュリティグループへは、EKS クラスタのセキュリティグループを送信元として、管理(443)・NFS(2049)・iSCSI(3260)の ingress を追加する。管理対象ノードグループのノードに付くのはこのクラスタ SG で、`ResourcesVpcConfig` に渡した追加 SG はコントロールプレーンの ENI 用であり、ノードには付かない [実測: 2026-10-29、ap-northeast-1、2 ノード、1 回観測]。
- CloudFormation で作れないもの: PV を生む Kubernetes オブジェクト(TridentBackendConfig / StorageClass / PersistentVolumeClaim)。これらはスタック完了後に kubectl / Helm で適用する。
- Trident EKS アドオンの名称・バージョンは変わりうるため、デプロイ前に `aws eks describe-addon-versions --addon-name netapp_trident-operator` で確認する。
- `KubernetesVersion` に既定値は無い。既定値は、標準サポートから延長サポートへ移ると、テンプレートを変えなくても古くなる(2026-10-29 時点の ap-northeast-1 では 1.31 が延長サポート [実測])。`aws eks describe-cluster-versions` で標準サポートの版を確認して指定する。

**iSCSI 使用時の注意(対称に記載)**: `ontap-san`(ブロック)を Amazon EBS CSI ドライバと併用する場合、ノードのマルチパス設定が EBS を掴まないよう `multipath.conf` で EBS デバイスを blacklist する必要がある(出典: 上記 EKS ユーザーガイドおよび Trident ドキュメント両方に記載)。

Amazon Linux 2023 の EKS AMI には iSCSI ツール(`iscsi-initiator-utils`、`device-mapper-multipath`、`lsscsi`)が入っていない(`nfs-utils` は入っている) [実測: 2026-10-29、ap-northeast-1、2 ノード、1 回観測]。テンプレートは launch template の user data で導入し、`multipath.conf` を書く。同じコマンドを SSM Run Command で実行すると SAN の PV が動作した [実測]。変更後のテンプレートをデプロイすると、user data がノードの初回起動で動き、パッケージの導入、`iscsid` と `multipathd` の起動、`multipath.conf` の内容が期待どおりになり、Trident の node pod は再起動なしに両ノードで iSCSI を検出した [実測: 2026-10-29、ap-northeast-1、2 ノード、1 回観測]。同じ日の別のデプロイでも手作業なしに同じ状態になり、SAN と NAS の PV でデータが残ることを確認した(4.3)。ただし `iscsid` の起動と kubelet の起動は同じ秒で、順序が保証される根拠は得ていない。node pod がツールの導入より先に起動した場合は、`trident-node-linux` の DaemonSet を再起動する。

### 4.3 構成 2 の実機確認結果

**範囲**: 2026-10-29 に 2 回、ap-northeast-1、既存の Single-AZ の FSx for ONTAP、各項目 1 回の観測。1 回目は 4.2 の launch template を加える前のリビジョン、2 回目は加えた後のリビジョンで行った。小規模の確認であり、連続運用、性能、Multi-AZ のフェイルオーバー、複数 Pod が同じファイルへ同時に書くときの整合は含まない。

| 項目 | 内容 |
|---|---|
| Kubernetes | v1.35(標準サポートの版) |
| ノード | m5.large × 2(別 AZ)、Amazon Linux 2023 |
| Trident アドオン | `netapp_trident-operator` v26.6.2-eksbuild.1(既定) |
| ONTAP | NetApp Release 9.18.1P6(2 回目で取得。1 回目は取得していない) |
| SVM | 検証用に作った専用 SVM。専用の `vsadmin` を設定 |
| バックエンドの認証 | Kubernetes Secret。Secrets Manager 参照(`awsarn`)は IRSA の追加設定が要るため試していない |
| StorageClass と PVC | `ontap-san` と `ontap-nas`、reclaim policy は `Delete`、1 GiB の PVC を各 1 本 |

| 系統 | 確認内容 | 結果 [実測] |
|---|---|---|
| iSCSI / RWO | PVC の払い出し | 約 10 秒で `Bound`(`ReadWriteOnce`) |
| iSCSI / RWO | マーカーの書き込み後、Pod の再起動後(同一ノード)、現ノードを cordon して Pod を削除した後(別ノード、別 AZ) | マーカーが 3 回とも一致。旧 Pod の削除が終わってから新 Pod が起動した。両ノードで同じ multipath デバイス(ext4)をマウント |
| NFS / RWX | PVC の払い出し | 約 10 秒で `Bound`(`ReadWriteMany`) |
| NFS / RWX | 別ノードの Pod A が書いた内容を Pod B が読む | 一致(NFS v4.2) |
| NFS / RWX | Deployment を再起動し、Pod がすべて新しくなった後 | 一致。再起動後の追記も別の Pod から読めた |

**観測の範囲**: 上の表の結果は 2 回とも同じだった。1 回目はノード準備を SSM Run Command で手作業で適用した。2 回目は手作業を挟まず、Trident の node Pod は再起動 0 回で、両ノードが iSCSI を使える状態(`tridentctl get node` で clean)になった。

| 系統 | 確認内容(2 回目) | 結果 [実測] |
|---|---|---|
| 既存ボリュームの取り込み | FSx の API で作ったボリュームに、PVC を使わない Pod がファイルを書く。アノテーション `trident.netapp.io/importOriginalName` と `trident.netapp.io/importBackendUUID` を付けた PVC で取り込む | 約 10 秒で `Bound`。取り込み前に書いたファイルを、取り込み後の Pod から読めた。ONTAP 上のボリューム名は `trident_pvc_…` に変わり、UUID とジャンクションパスは変わらなかった |
| 取り込みと reclaim policy | reclaim policy `Retain` の StorageClass で取り込み、PVC と PV オブジェクトを削除する | ONTAP 上のボリュームは残った。ただし Trident はボリュームの記録を持ち続け、TridentBackendConfig の削除は `Backend is in a deleting state` のまま進まなかった。`tridentctl delete volume <PV 名>` で記録を消すと削除が終わった |
| 資格情報の誤り | 誤ったパスワードの Secret を参照する TridentBackendConfig を作る | `Failed`、`401 (Unauthorized): incorrect or missing credentials`。PVC は `Pending` のままで、イベントは `no available backends for storage class` |
| 管理 LIF に到達できない | 使われていない IP を管理 LIF に指定する | `Failed`、`connect: no route to host`。PVC は `Pending` で同じイベント |
| 動いているバックエンドの Secret を書き換える | 正しいパスワードを誤った値に変える | バックエンドは再読み込みされるまで `Success` のままで、元の資格情報で動いた。再読み込み(TridentBackendConfig の spec の変更)で `Failed` になった。既存の Pod の読み書きは最後まで止まらず、止まったのは新しい PVC の払い出しだけだった |

**SVM ユーザーのロック**: 上の 2 つの失敗の試験のあと、正しいパスワードに戻しても認証が `401`(ONTAP のエラーコード 6691623)を返した。ONTAP 上で `vsadmin` がロックされていた。同じ `vsadmin` を使う SAN 側のバックエンドも `Failed` になった。ロックは自動では解けず、ファイルシステム管理者(`fsxadmin`)でロックを解除すると、両方のバックエンドが `Success` に戻り、待っていた PVC も `Bound` になった。誤ったパスワードでの認証が、資格情報の誤りの試験と再読み込みで繰り返されたためとみられる。ロックの閾値とロックされた時刻は読み取っていない。失敗の形を確かめるときは、別の SVM ユーザーを使うか、ほかの確認の後に行う。

**撤去の観測**: reclaim policy が `Delete` のとき、PVC を削除すると LUN とボリュームが ONTAP から消えた(ONTAP REST API で確認)。SAN の PVC を削除して 10 秒後の時点では SAN 用のボリュームがまだ残っており、削除は非同期である。このファイルシステムのバックアップ数は撤去の前後で変わらず、最終バックアップは作られなかった。ただしこのファイルシステムは自動バックアップの保持日数を返さなかったので、自動バックアップが有効な環境では未確認である。

**確認用 Deployment の注意**: Pod を別ノードに置く必須の分散指定と、ローリング更新の既定(`maxSurge` 25%)を組み合わせると、ノード数と Pod 数が同じとき、追加の Pod を置く場所がなく更新が止まった。`maxSurge: 0`、`maxUnavailable: 1` にして解消した。

FSx の API と ONTAP のボリューム一覧の差は 7.1 に記す。2 回目では、作成から約 55 分たった SVM の削除の時点で Trident のボリュームは FSx の API に出ておらず、SVM の削除は 1 回目の要求で受け付けられた。出現と消失の時刻は 2 回目では測っていない。

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

**この検証が言っていない範囲**: 構成 3・4 は、デプロイして動作することを検証していない。構成 1 の結果は 3.3、構成 2 の結果は 4.3 にある。以下は実機検証で確認する項目で、V1 は構成 1・2 の分、V2 は構成 2 の分を確認済みである。

| # | 項目 | 調査 / 検証の状態(2026-09-22) |
|---|---|---|
| V1 | 4 構成のデプロイとデータ疎通 | 構成 2 は 2026-10-29(4.3)、構成 1 は 2026-11-10(3.3)に確認 [実測]。構成 3・4 は未実施で、cfn-lint のみ [実測] |
| V2 | Trident EKS アドオンの現行名・バージョン | 2026-10-29 の ap-northeast-1 で `netapp_trident-operator` が存在し、既定は v26.6.2-eksbuild.1、対応する Kubernetes は 1.36 まで [実測]。名称と版は変わりうるため、デプロイ前に再確認する。Trident 26.10 と Kubernetes 1.37 は 9.3 |
| V3 | EKS Pod Identity の Fargate 対応可否 | 本メモは IRSA を採用。Pod Identity の Fargate 対応は未確認 [未測定] |
| V4 | S3 Access Point の UNIX ユーザーと ONTAP 側権限の対応 | 実機で権限設計を確認する必要あり [未測定] |
| V5 | S3 Access Point 経由の実効スループット | 文書は「ファイルシステムのプロビジョンドスループット依存」と記載。実測は未実施 [未測定] |

### 7.1 デプロイ準備(実機検証の前段)

上の V1〜V5 を実機で確認する前に踏む前提・順序・落とし穴・後始末を、やり直しを防ぐ観点でまとめる。実デプロイは課金と共有アカウント変更を伴うため、着手時に個別の承認を取る。

**前提: FSx for ONTAP は本リポジトリのテンプレート外** [実測]。5 テンプレートのいずれも `AWS::FSx::FileSystem` / `StorageVirtualMachine` / `Volume` を作らず、既存の FSx for ONTAP を参照する。デプロイの第 0 段階として、ファイルシステム + SVM + ボリュームを先に用意し、SVM の NFS エンドポイント・ボリュームのジャンクションパス・ファイルシステムのセキュリティグループ ID を控える(構成 1 の `FsxnSvmNfsEndpoint` / `FsxnVolumeJunctionPath` / `FsxnSecurityGroupId` に渡す)。

**確認済みの設計判断(実機で崩さない)**:

- 構成 1 のテンプレートは NFS マウントに `nfsvers=4.1` を明示している [実測]。NFSv4.1 が 2049 単一ポートで完結し、111 / 635 / 4045-4049 は NFSv3 用で v4.1 のみなら不要であることは AWS ドキュメントの記載である [文書](出典: [Use NFS to mount FSx for ONTAP volume on Linux instance](https://repost.aws/knowledge-center/ec2-mount-fsx-ontap-nfs))。本リポジトリでは 2026-11-10 に、ingress を 2049 のみにしたまま NFS v4.1 のマウントと読み書きが成立した [実測](3.3、1 回観測)。
- S3 Access Point ポリシーの循環は、Principal をアカウントルートにしロール側 identity policy で絞ることで回避済み(5.2)。

**着手前に確認する項目(V 番号に対応)**:

| 準備 | 対応する未検証項目 | 確認手段 |
|---|---|---|
| Trident EKS アドオンの現行名・バージョン | V2 | `aws eks describe-addon-versions --addon-name netapp_trident-operator`。2026-10-29 の ap-northeast-1 では v26.6.2-eksbuild.1 が既定で、本メモの 25.02 参照から進んでいる [実測] |
| S3 Access Point の二層認可(IAM + ファイルシステムレベルの UNIX / Windows ユーザー) | V4 | アクセスポイントに紐づく UNIX ユーザーと ONTAP 側のファイル権限の対応を実機で設計する [文書] |
| 対象リージョンでの提供 | V1 全般 | 第 2 世代 FSx for ONTAP は 2026-04 に 4 リージョン + GovCloud へ拡大。S3 Access Points は東京(ap-northeast-1)対応 [文書]。使うリージョンでの提供を確認する |
| IRSA の trust condition(EKS Fargate) | V3 | `sub` / `aud` はクラスタ作成後に手動で trust policy へ追加(5.2)。共用アカウントで未設定のまま放置しない |

**推奨デプロイ順序**: 最小の構成 1(ECS on EC2 + NFS、CloudFormation 完結・Trident 不要・S3 Access Points 不要)から始める。疎通(タスクから `/data` への読み書き)を確認したら削除し、構成 2(Trident の Kubernetes オブジェクトを kubectl / Helm で適用)、構成 3・4(S3 Access Points、IRSA の手動手順あり)へ段階的に進む。

**落とし穴(実機でやり直しを招く型)**:

- マウントはインスタンスの起動時処理で、タスクが作るものではない。マウント前にタスクが起動すると bind mount 先が空になる(3.2 に既述)。マウントを起動の前提条件として扱う。
- `ontap-san`(iSCSI)を Amazon EBS CSI ドライバと併用する場合、`multipath.conf` で EBS デバイスを blacklist しないとノードのマルチパスが EBS を掴む(4.2 に既述)。
- Trident の StorageClass / PVC / TridentBackendConfig は CloudFormation では作れない。スタック完了後に kubectl / Helm で適用する(4.2 に既述)。
- FSx の API は、Trident が ONTAP 側で作るボリュームを遅れて反映する。撤去後の残存確認を FSx の API だけで行うと、作成の直後は「無い」、削除の直後は「残っている」と読み違える。確認は ONTAP REST API(管理 LIF へ VPC 内から到達する)で行う。作成の 23 秒後と 11 分後の確認では FSx の API に出ず、26 分後の確認では出ていた。ONTAP で削除してから 41 分後の確認でもまだ残り、44 分後に消えた [実測: 2026-10-29、ap-northeast-1、1 回観測]。FSx の API 上に非ルートのボリュームが見えている間は、SVM の削除が `BadRequest` で拒否された。

**後始末(検証環境こそ確実に消す)**: 課金が続く主なリソースは FSx for ONTAP ファイルシステム(SSD 容量 + プロビジョンドスループットの時間課金)、EKS クラスタ、EC2 ノード / コンテナインスタンス、NAT / VPC エンドポイント。検証後にスタックを削除し、テンプレート外で先に作った FSx for ONTAP も忘れずに削除する。削除できない検証リソースは長期の請求になり、同居する他のリソースの操作も妨げる。

**Trident を使った場合の撤去順序**: スタックより先に、アプリの Deployment、PVC(SAN と NAS を別々に)、StorageClass、TridentBackendConfig の順で削除する。reclaim policy `Retain` の PV があるときは、PV オブジェクトを消しても Trident の記録が残るため、`tridentctl delete volume` で消してから TridentBackendConfig を削除する(4.3)。そのうえで、LUN とボリュームが ONTAP から消えたことを ONTAP REST API で確認する。その後にスタックを削除する。検証用に専用の SVM を作った場合は、FSx の API 上に非ルートのボリュームが見えなくなってから SVM を削除する。

---

## 8. 分割の判断

実機検証で実現性が確認できた場合、この一連の成果物(4 構成の CloudFormation + アプリ側の改修例)は、EC2 リホストの検証(既存)とは別のリポジトリ / Kiro プロジェクトに分割する余地がある。対象がソースコードとコンテナであり、検証スタック(ECS / EKS / Trident / S3 Access Points)が VMware 移行とは別系統になるためである。分割の是非は実機検証の後に判断する。

---

## 9. 2026-10〜11 の EKS・コンテナ更新と本構成への影響

**調査範囲**: 2026-11-10 に、EKS ユーザーガイドの Document history(2026-10-10 以降の項目)、AWS What's New 2 件(DRA、Gateway API)、各機能の公式ドキュメント、NetApp Trident 26.10 のリリースノートと要件ページを全文で読んだ。KubeCon North America 2026(11/9〜12)の発表は検索結果の要約しか見ておらず、本文は読んでいない [未測定]。EKS アドオンの版(9.3)、Nitro Sandbox と Trident の PV(9.1)、Auto Mode と Trident(9.2)は同日に ap-northeast-1 で実機を確かめた。それ以外は [文書] で、本リポジトリで動かしたものは無い。

Trident のドライバ選択(`ontap-nas` と `ontap-san`、Windows の SMB PV は Windows ノードのみ)は Hub の[コンテナデータストア選定](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/reference/decision-trees/container-datastore-selection.md)にある。同ページは Nitro Sandbox、Auto Mode、Trident 26.10 を扱っていないため、本章はその差分である。 <!-- spoke-checked: ontap-nas -->

| 更新 | 構成 2(EKS on EC2 + Trident)への影響 | 構成 3・4(Fargate + S3 Access Points)への影響 |
|---|---|---|
| Nitro Sandbox による Pod 単位の隔離(`isolated-sandbox` / `confidential-sandbox`) | 9.1 | 9.1 |
| EKS Auto Mode と Karpenter の DRA 対応 | 9.2 | なし |
| Trident 26.10 と Kubernetes 1.37 | 9.3 | なし |
| Auto Mode の Gateway API、Argo CD 機能の更新、`ec2:CopyVolumes` | 9.4 | なし |

### 9.1 Nitro Sandbox の隔離 Pod とストレージ

Pod ごとに専用の Nitro Sandbox(Firecracker の microVM)で動かす機能で、`runtimeClassName` を Pod 単位で指定する。指定しない Pod は従来のランタイムのままである。EC2 上のノードだけが対象で、Fargate の Pod には関係しない(出典: [Sandboxing on Amazon EKS](https://docs.aws.amazon.com/eks/latest/userguide/sandboxing.html))。

ストレージについて、ドキュメントが挙げる方式は次のとおり(出典: [Storage with Nitro Sandboxes](https://docs.aws.amazon.com/eks/latest/userguide/sandboxing-storage.html))。

- Amazon EBS CSI: ブロックデバイスとして Sandbox に接続する。`ReadWriteOncePod` を使い、1 つのボリュームを複数 Pod で共有できない。
- Amazon EFS CSI(アドオン 3.5.0 以上): NFS のマウントと TLS の終端を Sandbox の内側で行う。
- tmpfs を使う CSI ドライバ(Secrets Store、cert-manager)と、`emptyDir` / ConfigMap / Secret。

**Trident(`csi.trident.netapp.io`)による NFS / iSCSI の PV は、このページに記載が無い。** 「サポートされない」とも書かれておらず、対応の有無は文書から判断できなかったため、実機で確かめた。

**実機の結果** [実測: 2026-11-10、ap-northeast-1、各ケース 1 回の観測]。EKS Auto Mode のクラスタ(Kubernetes v1.36.4、Trident アドオン v26.6.2-eksbuild.1)で、同じ NFS の PVC(RWX、1 GiB、使い捨て SVM)を通常の Pod と `runtimeClassName: isolated-sandbox` の Pod にマウントした。

| ケース | 結果 |
|---|---|
| 通常の Pod 2 本(別ノード)が NFS の PVC をマウント | 成立。片方が書いたマーカーをもう片方が読めた |
| 隔離 Pod が同じ NFS の PVC をマウント | **失敗**。コンテナの作成が `failed to fulfil mount request: open …/volumes/kubernetes.io~csi/pvc-…/mount: no such file or directory` で止まり、約 6 分の間に再起動 5 回で `CrashLoopBackOff`。PVC の払い出しと Attach は成功していた |
| 対照: 隔離 Pod が `emptyDir` だけを使う | 成立。Pod 内のカーネルは 6.18.54、通常ノードは 6.18.56 で、別のカーネルで動いている |
| 対照: 隔離 Pod が Amazon EBS の PVC(Auto Mode の EBS CSI)をマウント | 成立。書き込みと読み戻しができた |

隔離 Pod は同じクラスタ、同じノード種別(c8a.large)で成立しており、EBS の PVC も使えた。失敗したのは Trident の NFS の PV だけである。この結果は、同ページがストレージとして挙げた方式に Trident が含まれないことと整合する。AWS のサンプル集には、隔離 Pod の永続ストレージとして `ebs`、`efs`、`s3-files` の 3 つのブループリントがある(出典: [sample-eks-nitro-sandbox の storage](https://github.com/aws-samples/sample-eks-nitro-sandbox/tree/main/examples/storage))。FSx for ONTAP を隔離 Pod の永続ストレージにする公開された手順は見つかっていない。失敗の原因そのもの(NodePublish がホスト側で完了しているのに Sandbox にマウント先が引き渡されない、といった推測)は、Trident の info レベルのログに記録が無く、切り分けていない。1 回の観測で、再現と別バージョンでの挙動は未確認である。

iSCSI の PV を隔離 Pod に渡せるかは、Auto Mode のノードで iSCSI 自体が使えなかったため(9.2)、確かめられていない。`sandbox.amazonaws.com/network-isolated: "true"` の Pod はネットワークデバイスを持たず、EFS は使えないと明記されている。同じ理由でネットワーク経由の FSx for ONTAP にも到達できないと推測するが、これは試していない。

構成 3・4 で使う S3 Access Points のオブジェクト API は、ネットワーク経由の SDK 呼び出しなので、Sandbox の Pod からも原理的には使える。ただし認証は注意が要る。隔離モードではサービスアカウントのトークンが Sandbox に複製されず、IMDS からは認証情報を取れない(配置情報の 5 パスのみ応答する)。一方で EKS Pod Identity の認証情報は許可されている。構成 4 の IRSA(サービスアカウントのトークンを使う)が隔離モードの Pod で動くかは確認しておらず、Pod Identity を使う設計が文書上は素直である。なお V3 のとおり、Pod Identity の Fargate 対応は別途未測定である。

Sandbox に制約が多い項目(`hostNetwork: true` で起動失敗、`hostUsers: false` 非対応、GPU 非対応、Pod あたりの vCPU 密度の上限など)は、Trident の node pod そのものには当たらないと推測する。node pod が使うのは通常のランタイムで、Sandbox を指定するのはアプリケーションの Pod だからである。この点も文書に明記はない。

### 9.2 Auto Mode と Karpenter の DRA 対応

DRA(Dynamic Resource Allocation)の対象は NVIDIA GPU と EFA で、ストレージのデバイスは対象外である(出典: [What's New](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-eks-auto-mode-karpenter-dra/))。FSx for ONTAP の PV の払い出しや到達経路は変わらない。Auto Mode の DRA は Kubernetes 1.36 以上、Karpenter は全バージョンが対象である。

間接的な影響は 1 点ある。GPU を使う AI ワークロードが共有データを FSx for ONTAP に置く構成では、Auto Mode の管理ノードにソフトウェアを導入できない(AMI は AWS が決め、SSH もできない)ことが、構成 2 の iSCSI 用ノード準備(4.2 の launch template)と衝突する(出典: [Learn about Amazon EKS Auto Mode Managed instances](https://docs.aws.amazon.com/eks/latest/userguide/automode-learn-instances.html))。このため、本リポジトリの `PrepareNodesForIscsi` の方式は Auto Mode のノードには適用できない。文書には Auto Mode での Trident の可否が見つからなかったため、9.1 と同じクラスタで実機を確かめた。

**実機の結果** [実測: 2026-11-10、ap-northeast-1、各ケース 1 回の観測。Kubernetes v1.36.4、ノードは Bottlerocket(EKS Auto, Standard)2026.10.31、Trident アドオン v26.6.2-eksbuild.1]。

| ケース | 結果 |
|---|---|
| Trident アドオンの導入 | ノードが無い状態から、Pod の保留をきっかけに Auto Mode がノードを起動し、node pod とコントローラが Running になった。起動中はアドオンが `DEGRADED`(`InsufficientNumberOfReplicas`)と表示され、ノードの起動後に解消した |
| バックエンド(NFS と iSCSI の 2 本)と PVC の払い出し | どちらも `Success` / `Bound`。払い出しはコントローラ側の処理で、ノードのツールは要らない |
| NFS の PV を Pod にマウント | **成立**。ノード 2 台にまたがる Pod 間で書いたマーカーを読めた。新しいノードでは Trident の node pod が登録されるまで `CSINode … does not contain driver` で数十秒失敗してから成功した |
| iSCSI の PV を Pod にマウント | **失敗**。`unable to attach: open-iscsi tools not found on host`。`tridentctl get node` の IQN と SERVICES が空で、ログは `Could not read initiatorname.iscsi; perhaps iSCSI is not installed?` |

したがって、Auto Mode の管理ノードでは NFS の PV は使え、iSCSI の PV は使えない。AMI を選べず、ノードにソフトウェアを導入できないため、構成 2 の `PrepareNodesForIscsi` の方式で補うこともできない。iSCSI(ブロック)が要る場合は、managed node group など AMI を制御できるノードを使う。Auto Mode でのこの結果は 1 回の観測で、将来の AMI 更新で変わりうる。

### 9.3 Trident 26.10 と Kubernetes 1.37

- EKS は Kubernetes 1.37 を 2026-10-01 に追加した(出典: [Document history](https://docs.aws.amazon.com/eks/latest/userguide/doc-history.html))。Trident 26.10 は Kubernetes 1.27〜1.37 に対応する(出典: [Trident requirements](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html))。テンプレートの `KubernetesVersion` のパターンは 1.37 を許容する。
- 4.3 と V2 の実機確認で使った EKS アドオンの既定は v26.6.2-eksbuild.1 で、対応する Kubernetes は 1.36 まで(2026-10-29)だった [実測]。2026-11-10 の ap-northeast-1 で再確認すると、アドオンの最新は同じ v26.6.2-eksbuild.1(既定)で、対応は Kubernetes 1.36 までだった。26.10.x のアドオンはまだ無く、1.37 に対応する版も無い [実測: 1 回観測]。同じ日に EKS は 1.34〜1.37 が標準サポートだった。したがって、アドオンを使う構成 2 のテンプレートは、現時点では Kubernetes 1.36 以下を指定する。1.37 で Trident 26.10.1 を使うには、アドオンではなく Helm の trident-operator チャートで導入する経路になる。この Helm 導入の手順は兄弟リポジトリ blea-fsxn-usecase の[サンプル](https://github.com/Yoshiki0705/blea-fsxn-usecase/blob/main/usecases/blea-guest-fsxn-modernization-sample/doc/README_ja.md)に記載があるが、Trident 26.10.1 と Kubernetes 1.37 の組での実行記録は見つかっていない。本リポジトリでも試していない。 <!-- spoke-checked: helm -->
- **Trident 26.10(26.10.1 より前)にはアップグレードしない。** リリースノートによると、起動時に node pod が使用中のボリュームを切り離し、Pod が `volume … is not staged` で失敗することがある。26.10.1 で修正された(出典: [Trident release notes](https://docs.netapp.com/us-en/trident/trident-rn.html))。アドオンの版を固定するときは 26.10.1 以降を選ぶ。
- 本リポジトリの構成に関係する 26.10 の変更(リリースノートの記載で、本リポジトリでは動かしていない): `ontap-san` / `ontap-san-economy` で新規ボリュームの ONTAP オートサイズ、一部の iSCSI パスが使えない状態でのボリューム拡張、`enableConcurrency` 有効時に ONTAP-NAS のエクスポートポリシーのルールが誤って消える不具合の修正、PVC のアノテーション `trident.netapp.io/unixGroupID`(ルートスカッシュのある ONTAP-NAS ボリューム)。

### 9.4 構成 2 の運用に関わるその他の更新

- EKS Auto Mode の Gateway API 対応(2026-10): ALB / NLB による通信制御で、ストレージの経路には関与しない。
- EKS Capability for Argo CD の通知、ApplicationSet の webhook、source hydrator(2026-10〜11): 4.2 のとおり、TridentBackendConfig / StorageClass / PVC は CloudFormation で作れず、スタック完了後に kubectl などで適用する。この適用を GitOps に載せる選択肢になりうるが、本リポジトリでは試していない。 <!-- spoke-checked: helm -->
- `ec2:CopyVolumes`(2026-10-26): Auto Mode の EBS CSI が、スナップショットなしで既存の PVC から別の PVC を作るための権限である。EBS ボリュームが対象で、FSx for ONTAP の PV には関与しない。

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
- [Sandboxing on Amazon EKS with isolated and confidential pods](https://docs.aws.amazon.com/eks/latest/userguide/sandboxing.html)
- [Storage with Nitro Sandboxes](https://docs.aws.amazon.com/eks/latest/userguide/sandboxing-storage.html)
- [Amazon EKS Auto Mode and Karpenter now support Dynamic Resource Allocation](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-eks-auto-mode-karpenter-dra/)
- [Learn about Amazon EKS Auto Mode Managed instances](https://docs.aws.amazon.com/eks/latest/userguide/automode-learn-instances.html)
- [Amazon EKS User Guide: Document history](https://docs.aws.amazon.com/eks/latest/userguide/doc-history.html)
- [Trident release notes](https://docs.netapp.com/us-en/trident/trident-rn.html)
- [Trident requirements](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html)
- [コンテナ化への派生と FSx for ONTAP の連携可否(本リポジトリ)](atx-containerization-fsxn-derivation.md)
