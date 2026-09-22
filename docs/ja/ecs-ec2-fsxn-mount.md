# ECS on EC2 における FSx for ONTAP のマウント

**目的**: Amazon ECS の EC2 起動タイプで Amazon FSx for NetApp ONTAP をコンテナのデータ領域として使う方法を、AWS 公式のホストマウント方式(NFS / SMB)を軸に網羅する。あわせて、NetApp Trident をコンテナとして ECS on EC2 に組み込む経路の可否を一次情報で判定し、確信度を分けて記録する。

**最終更新**: 2026-09-22
**ステータス**: 文献調査 + ドキュメント化。実機マウント確認は未実施(Trident on ECS の実機検証は次段階に計画)

関連: [コンテナ移行先での FSx for ONTAP データストア構成の検証](atx-containerization-fsxn-storage-verification.md) の構成 1 を、この文書で手順レベルまで掘り下げる。

---

## 1. 結論

ECS on EC2 で FSx for ONTAP を使う確立した方法は、**EC2 コンテナインスタンスがボリュームをマウントし、タスクへ bind mount する**方式である(出典: [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html))。

| 経路 | 到達形態 | コンテナ OS | 確信度 |
|---|---|---|---|
| Linux + NFS | ホストが NFS マウント → `host.sourcePath` で bind mount | Linux | [文書] |
| Windows + SMB | ホストが SMB グローバルマッピング → bind mount | Windows | [文書] |
| Trident(Docker プラグイン)経由 | ホストの Docker ボリュームドライバとして Trident → タスク定義の `dockerVolumeConfiguration` で参照 | Linux | [未確認] |

**Trident についての訂正**: 本プロジェクトの過去のやり取りで「Trident は Kubernetes 専用であり ECS では使えない」と記述したが、これは誤りである。Trident は Docker ボリュームプラグインとしても提供されており、Kubernetes に依存しない(3 章)。ECS on EC2 での組み込みは原理的に成立しうるが、AWS / NetApp のどちらも「ECS + Trident Docker プラグイン」を公式にサポート/テスト済みと明記した記載は本調査時点(2026-09-22)で見つからなかった。よって [未確認] とし、実機検証を次段階に置く(5 章)。

---

## 2. エビデンス区分

| タグ | 意味 |
|---|---|
| **[実測]** | 本リポジトリで実際に実行して確認済み |
| **[文書]** | AWS / NetApp 公式ドキュメントの記載。出典 URL を併記。実機確認は意味しない |
| **[未確認]** | 実行しておらず公開情報でも裏取りできていない。調査日と調査範囲を併記 |

---

## 3. AWS 公式のホストマウント方式

### 3.1 Linux コンテナと NFS [文書]

手順は次の順序になる(出典: 上記 ECS ユーザーガイド)。

1. EC2 Linux + Networking のクラスタテンプレートで ECS クラスタを作る。
2. コンテナインスタンスにマウント先ディレクトリを作る(例 `/fsxontap`)。
3. SVM ボリュームを NFS でマウントする。起動時の user-data か、手動コマンドで行う。

```
sudo mount -t nfs -o nfsvers=4.1 svm-dns-name:/volume-junction-path /fsxontap
```

4. タスク定義に `volumes`(`host.sourcePath`)と `mountPoints` を追加し、ホストのマウント先をコンテナへ bind mount する。

### 3.2 NFS マウントの既定と注意 [文書]

- FSx for ONTAP の NFS マウントは既定で **hard マウント**である。フェイルオーバーを円滑にするため、既定の hard マウントの使用が推奨される(出典: [Mounting volumes on Linux clients](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/attach-linux-client.html))。
- SVM の DNS 名でも IP でもマウントできる。NFS のバージョンは `nfsvers` で指定する。
- ONTAP は NFS の I/O サイズを既定で 64K に制限する [文書](出典: [PostgreSQL databases with NFS Filesystems](https://docs.netapp.com/us-en/ontap-apps-dbs/postgres/postgres-nfs-filesystems.html))。

### 3.3 Windows コンテナと SMB [文書]

1. EC2 Windows + Networking のクラスタテンプレートで ECS クラスタを作る。
2. ドメイン参加した EC2 Windows インスタンスを追加し、`Initialize-ECSAgent -Cluster <cluster> -EnableTaskIAMRole` で ECS エージェントを初期化する。
3. `New-SmbGlobalMapping` で SMB 共有をドライブ(例 `Z:`)にマッピングする。NFS でマウントしていた同じボリューム(`vol1`)を CIFS 共有として公開できる。
4. タスク定義に `volumes` と `mountPoints` を追加し、コンテナへ bind mount する。

### 3.4 ネットワークとセキュリティグループ [文書]

- NFS はポート 2049、SMB はポート 445 を、ECS インスタンスから FSx for ONTAP のセキュリティグループへ許可する。
- FSx for ONTAP と ECS インスタンスは相互に到達可能な VPC に配置する。SVM のエンドポイント(DNS / IP)への到達性が前提。

### 3.5 マウントのライフサイクル [文書 + 未確認]

- マウントはコンテナインスタンスの処理(user-data / `fstab`)であり、タスクが作るものではない。
- **マウント前にタスクが起動すると、bind mount 先が空になる** [文書の含意]。マウントを起動の前提条件として扱う。マウント失敗時にタスクをどう扱うか(再試行・ヘルスチェック)は運用設計側の課題で、実挙動は未検証 [未確認]。

### 3.6 認証と権限 [文書 + 未確認]

- Linux + NFS: ホストが NFS でマウントするため、ファイルアクセスはホストの UID/GID と ONTAP のエクスポートポリシーに従う。タスクロール(IAM)はマウント自体には関与しない。
- Windows + SMB: SVM が Active Directory に参加し、SMB 認証は AD 資格情報で行う。AD 参加の前提は別リポジトリの [AD 統合の手順](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/ja/ad-integration-for-migration.md) を参照。
- NFS の UID/GID マッピングと ONTAP 側権限の具体的な対応は、実機で確認する必要がある [未確認]。

### 3.7 ECS のデーモン機構との関係 [文書]

前回の議論の接続として、ECS でホスト単位に常駐タスクを置く仕組みは 2 つある。

- **daemon スケジューリング戦略**: サービスの `schedulingStrategy: DAEMON`。EC2 起動タイプで各コンテナインスタンスに 1 タスクを配置する。
- **ECS Managed Daemons**: Amazon ECS Managed Instances のキャパシティプロバイダの各 EC2 に 1 デーモンタスクを配置・管理する新機能。ログ・トレース・セキュリティエージェントを想定(出典: [Amazon ECS Managed Daemons](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-daemons.html))。

どちらも「ECS タスクを各インスタンスに配る」仕組みであって、Kubernetes の CSI ランタイムを提供するものではない。NFS/SMB ホストマウント方式(3.1〜3.3)はデーモン機構を必要としない。マウントはインスタンスの起動処理で足りる。

### 3.8 制約と代替 [文書]

- この方式は EC2 起動タイプ専用。Fargate はホストにマウントできないため使えない(Fargate は S3 Access Points 経由のオブジェクトアクセスを使う。[検証メモ](atx-containerization-fsxn-storage-verification.md) の構成 3・4)。
- ECS と FSx for Windows File Server の組み合わせは Windows EC2 のみで、Linux EC2 と Fargate は対象外(出典: [Use FSx for Windows File Server volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/wfsx-volumes.html))。本文書の対象は FSx for ONTAP。
- bind mount のため、複数タスクで同一ホストのマウントを共有する形になる。共有の粒度はホスト単位。

---

## 4. Trident をコンテナとして組み込む経路

### 4.1 Trident for Docker の存在 [文書]

Trident は Kubernetes の CSI ドライバとしてだけでなく、**Docker ボリュームプラグイン**としても提供されている(出典: [Deploy Trident for Docker](https://docs.netapp.com/us-en/trident/trident-docker/deploy-docker.html))。Kubernetes に依存しない。要件ドキュメントの一節がこの性質を述べている: Trident はコンテナで動く一プロセスであり、どの Linux ワーカーでも動く。ボリュームの実マウントはワーカー側の標準 NFS クライアント / iSCSI イニシエータが担う(出典: [Requirements](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html))。

Docker マネージドプラグイン方式の要点:

```
docker plugin install --grant-all-permissions --alias netapp \
  netapp/trident-plugin:<version> config=myConfigFile.json
docker volume create -d netapp --name firstVolume
docker run --rm -it --volume-driver netapp --volume secondVolume:/my_vol alpine ash
```

設定ファイル(`/etc/netappdvp/config.json`)に `storageDriverName`(`ontap-nas` / `ontap-san`)、`managementLIF` / `dataLIF`、`svm`、`username`(`vsadmin`)、`aggregate` を指定する。

### 4.2 ECS の Docker ボリュームドライバ対応 [文書]

ECS on EC2 のタスク定義は、`dockerVolumeConfiguration` の `driver` で**サードパーティの Docker ボリュームドライバ**を指定できる(出典: [Use Docker volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/docker-volumes.html))。制約は以下。

- Docker ボリュームは **EC2 起動タイプ専用**。Fargate は非対応。
- Windows コンテナは `local` ドライバのみ対応。
- ボリュームは Docker が管理し、コンテナインスタンスの `/var/lib/docker/volumes` にデータ用ディレクトリが作られる。

### 4.3 2 つを組み合わせた場合の判定 [未確認]

4.1 と 4.2 を組み合わせると、次の経路が原理的に成立しうる。

1. ECS の EC2 コンテナインスタンスに Trident の Docker プラグインを導入する(`docker plugin install netapp/trident-plugin`)。
2. FSx for ONTAP を backend に設定する(`storageDriverName: ontap-nas` 等、SVM の LIF を指定)。
3. タスク定義の `dockerVolumeConfiguration` で `driver: netapp` を参照し、コンテナへボリュームをマウントする。

Trident の backend として FSx for ONTAP はサポート対象に挙がっている(出典: [Requirements の Supported backends](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html))。

**ただし、この組み合わせを公式にサポート/テスト済みと明記した記載は、本調査時点(2026-09-22)で AWS / NetApp のどちらにも見つからなかった** [未確認]。確認した範囲: ECS のドキュメント(docker-volumes.html、specify-volume-config.html)、Trident の Docker デプロイ手順、Trident の要件ページ。したがって:

- 「2 つの文書化された機構(ECS のサードパーティボリュームドライバ、Trident for Docker)の組み合わせで成立しうる」までは言える。
- 「ECS + Trident Docker プラグイン + FSx for ONTAP が動く」ことは**確認していない**。公式サポートの裏取りも無い。

この区別を曖昧にすると誤った設計判断を招く。実機検証(5 章)で確認するまでは [未確認] のまま扱う。

### 4.4 NFS ホストマウント方式との違い [文書 + 未確認]

| 観点 | NFS ホストマウント(3 章) | Trident Docker プラグイン(4 章) |
|---|---|---|
| ボリュームの作成 | 事前に ONTAP 側でボリューム作成、ホストが手動マウント | Trident が要求時にプロビジョン(`docker volume create`) |
| 制御面 | OS の mount / fstab | Trident(`docker volume` / 設定ファイル) |
| 動的プロビジョニング | なし(静的) | あり(Trident が払い出す) |
| 公式サポートの明記 | あり(AWS ECS ユーザーガイド)[文書] | 見つからず [未確認] |
| ONTAP 機能(Snapshot/クローン) | ONTAP 側で別途運用 | Trident のドライバ機能として利用しうる(未確認) |

動的プロビジョニングや ONTAP 機能連携が要らないなら、確立した NFS ホストマウント方式で足りる。Trident Docker プラグイン経路の利点(動的プロビジョン等)が要る場合に、次段階の実機検証で可否を確かめる。

---

## 5. Trident on ECS の実機検証(次段階の設計)

このセッションでは実機検証を行わない。実現性が確認できた場合に実施する手順を設計として残す。実行前に、EC2 インスタンス起動・FSx for ONTAP への接続・共用検証アカウントへの変更を伴うため個別の承認を得る。

1. **準備**: ECS on EC2 クラスタ(既存の [構成 1 テンプレート](../../templates/containers-ecs-ec2-fsxn-nfs.yaml) を土台にできる)、FSx for ONTAP ファイルシステムと SVM、SVM の管理 LIF / データ LIF、`vsadmin` 資格情報(Secrets Manager)。
2. **プラグイン導入**: コンテナインスタンスの起動処理で `docker plugin install netapp/trident-plugin:<version> config=...` を実行。設定に FSx for ONTAP の SVM と `ontap-nas`(または `ontap-san`)を指定。
3. **タスク定義**: `dockerVolumeConfiguration` で `driver: netapp`、`autoprovision` の要否を確認。
4. **検証項目**:
   - プラグインが FSx for ONTAP に接続し、ボリュームをプロビジョン/マウントできるか。
   - `ontap-san`(iSCSI)使用時、ノードのマルチパス設定と EBS の競合(`multipath.conf` で EBS を blacklist する必要)を回避できるか。
   - タスク再起動・インスタンス入れ替え時のマウントの再現。
   - NFS ホストマウント方式(3 章)との運用差(動的プロビジョン、ONTAP 機能)。
5. **記録**: できた/できなかった/条件付きで成立、を本文書の 4.3 に反映し、[未確認] を [実測] へ更新する。

---

## 6. 未確認事項

| # | 項目 | 調査 / 検証の状態(2026-09-22) |
|---|---|---|
| E1 | ECS + Trident Docker プラグイン + FSx for ONTAP の統合可否 | 原理的に成立しうる(4.3)。公式サポートの明記は見つからず。実機未検証 [未確認] |
| E2 | マウント失敗時の ECS タスクの実挙動 | 未検証。運用設計側の課題 [未確認] |
| E3 | NFS の UID/GID と ONTAP エクスポートポリシーの具体的対応 | 実機で確認要 [未確認] |
| E4 | Trident Docker プラグインの `ontap-san` 使用時の EBS multipath 競合回避 | Kubernetes 経路では blacklist 必須と判明済み。Docker プラグイン経路での挙動は未検証 [未確認] |

---

## 参考リンク

- [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html)
- [Mounting volumes on Linux clients(FSx for ONTAP)](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/attach-linux-client.html)
- [Use FSx for Windows File Server volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/wfsx-volumes.html)
- [Amazon ECS Managed Daemons](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-daemons.html)
- [Use Docker volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/docker-volumes.html)
- [Specify a Docker volume in an Amazon ECS task definition](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specify-volume-config.html)
- [Deploy Trident for Docker](https://docs.netapp.com/us-en/trident/trident-docker/deploy-docker.html)
- [Trident Requirements(supported frontends / backends)](https://docs.netapp.com/us-en/trident/trident-get-started/requirements.html)
- [コンテナ移行先での FSx for ONTAP データストア構成の検証(本リポジトリ)](atx-containerization-fsxn-storage-verification.md)
- [AD 統合の手順(別リポジトリ VMware-Migration-EC2-ONTAP)](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/ja/ad-integration-for-migration.md)
