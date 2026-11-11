#!/usr/bin/env python3
"""Generate the architecture diagrams from a spec, one file per language and theme.

Provenance: the machinery here -- direct `.drawio` XML generation, icons embedded as
`data:image/svg+xml,<base64>` data URIs, `--check` against the committed files, and
`stabilize_svg()` -- is copied from `tools/build_diagrams.py` in the sibling repository
`FSx-for-ONTAP-Adoption-Playbook`, which took it from `S3-Burst-on-ONTAP-Files`. What changed:
the spec functions, the label table, and the icon list are this repository's; the Google Cloud
icon handling is removed because no figure here uses it.

Why the XML is written directly rather than through the draw.io MCP tools or the built-in
`mxgraph.aws4.*` shapes -- each was tried in a sibling project:

* `insert_image_vertex` embeds icons in a form the draw.io CLI drops on export, so the picture is
  right on screen and empty in the exported file;
* `mxgraph.aws4.*` carries the 2019 icon generation, not the current quarterly asset package;
* the data URI must be `data:image/svg+xml,<base64>`. Written as the MIME specification would
  suggest, `data:image/svg+xml;base64,`, draw.io renders nothing and the export still succeeds.

Icons are read from the AWS Architecture Icons package rather than copied in. The package is a
quarterly release from https://aws.amazon.com/architecture/icons/ and is never committed, so this
is an authoring step and not a gate: the generated `.drawio` and the exported images are the
committed artefacts, and `make ci` runs the two checkers on those.

Run:
  python3 tools/build_diagrams.py --check           # committed files still match the spec
  python3 tools/build_diagrams.py --write           # regenerate every .drawio
  python3 tools/build_diagrams.py --write --export  # and run the draw.io CLI for SVG + PNG
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
DIAGRAM_DIR = ROOT / "docs" / "_assets" / "diagrams"
IMAGE_DIR = ROOT / "docs" / "_assets" / "images"
PNG_DIR = IMAGE_DIR / "png"

LANGS = ("ja", "en")
THEMES = ("light", "dark")

# Fixed so regeneration is byte-stable. A changing timestamp puts every diagram in every diff and
# hides the edit that mattered.
MODIFIED = "2026-08-28T00:00:00.000Z"
DRAWIO_CLI = Path("/Applications/draw.io.app/Contents/MacOS/draw.io")

# --- icons ---------------------------------------------------------------------------------------

# Relative to the package root, with `{d}` standing for the release date and `{v}` for the
# light/dark variant of the general resource icons. The date is read off the directory name, so
# there is one home for one fact.
ICONS = {
    "fsx_ontap": (
        "Architecture-Service-Icons_{d}/Arch_Storage/64/"
        "Arch_Amazon-FSx-for-NetApp-ONTAP_64.svg"
    ),
    "ec2": "Architecture-Service-Icons_{d}/Arch_Compute/64/Arch_Amazon-EC2_64.svg",
    "lambda": "Architecture-Service-Icons_{d}/Arch_Compute/64/Arch_AWS-Lambda_64.svg",
    "ecs": (
        "Architecture-Service-Icons_{d}/Arch_Containers/64/"
        "Arch_Amazon-Elastic-Container-Service_64.svg"
    ),
    "eks": (
        "Architecture-Service-Icons_{d}/Arch_Containers/64/"
        "Arch_Amazon-Elastic-Kubernetes-Service_64.svg"
    ),
    "athena": (
        "Architecture-Service-Icons_{d}/Arch_Analytics/64/Arch_Amazon-Athena_64.svg"
    ),
    "glue": "Architecture-Service-Icons_{d}/Arch_Analytics/64/Arch_AWS-Glue_64.svg",
    "emr": "Architecture-Service-Icons_{d}/Arch_Analytics/64/Arch_Amazon-EMR_64.svg",
    "bedrock": (
        "Architecture-Service-Icons_{d}/Arch_Artificial-Intelligence/64/"
        "Arch_Amazon-Bedrock_64.svg"
    ),
    "transfer": (
        "Architecture-Service-Icons_{d}/Arch_Migration-Modernization/64/"
        "Arch_AWS-Transfer-Family_64.svg"
    ),
    "cloudfront": (
        "Architecture-Service-Icons_{d}/Arch_Networking-Content-Delivery/64/"
        "Arch_Amazon-CloudFront_64.svg"
    ),
    "ebs": (
        "Architecture-Service-Icons_{d}/Arch_Storage/64/"
        "Arch_Amazon-Elastic-Block-Store_64.svg"
    ),
    # Resource icons: a single file with no Light/Dark variant, so no `{v}`. Placed at 48.
    "vpc_endpoint": (
        "Resource-Icons_{d}/Res_Networking-Content-Delivery/"
        "Res_Amazon-VPC_Endpoints_48.svg"
    ),
    # The resource icon for an access point, which the standard prefers over the generic bucket.
    "s3_access_point": (
        "Resource-Icons_{d}/Res_Storage/"
        "Res_Amazon-Simple-Storage-Service_General-Access-Points_48.svg"
    ),
}

# Icons that are not AWS assets. The AWS package (07312026, the latest quarterly release when this
# was written) has an Amazon EKS service icon but no icon for EKS Auto Mode, a pod, or a
# PersistentVolume; its only EKS resource icon is EKS on Outposts. For the Kubernetes objects the
# figures use the Kubernetes community icon set, which exists to standardize Kubernetes
# architecture diagrams and is licensed Apache-2.0 or CC-BY-4.0
# (https://github.com/kubernetes/community/tree/main/icons). EKS Auto Mode is a mode of Amazon EKS,
# so it is drawn with the Amazon EKS service icon and a qualifier line, as the naming rule asks.
#
# The files live under docs/_assets/icons/, which is gitignored: as with the AWS package, what gets
# committed is the finished diagram with the icon embedded, not the icon as a file of its own.
LOCAL_ICON_DIR = ROOT / "docs" / "_assets" / "icons"
# NetApp Trident is drawn with the logo its own repository publishes (logo/trident.png in
# https://github.com/NetApp/trident, the file its README shows). It is the only logo file there:
# there is no dark variant, and recolouring a product mark is not ours to do, so on the dark canvas
# the same logo sits on a white plate instead (PLATED_ICONS).
LOCAL_ICONS = {
    "k8s_pod": "k8s-pod.svg",
    "k8s_pv": "k8s-pv.svg",
    "trident": "netapp-trident.png",
}
LOCAL_ICON_URLS = {
    "k8s_pod": (
        "https://raw.githubusercontent.com/kubernetes/community/"
        "307ae50e8e4246de172f195c73e3f026b4f0c7ff/icons/svg/resources/unlabeled/pod.svg"
    ),
    "k8s_pv": (
        "https://raw.githubusercontent.com/kubernetes/community/"
        "307ae50e8e4246de172f195c73e3f026b4f0c7ff/icons/svg/resources/unlabeled/pv.svg"
    ),
    "trident": (
        "https://raw.githubusercontent.com/NetApp/trident/"
        "6fe65ee071e24485b85ccfed2d17c703fcec7977/logo/trident.png"
    ),
}
# A data URI needs the type that matches the bytes. Getting it wrong exports a broken-image
# placeholder while still reporting success.
MIME_BY_SUFFIX = {".png": "image/png", ".svg": "image/svg+xml"}
# Marks drawn on a white plate on the dark canvas, because the mark has no dark variant.
PLATED_ICONS = {"trident"}

# Native sizes. Rescaling is what the AWS icon guidelines forbid, so the size follows the asset:
# 80 for an architecture (service) icon, 48 for a resource icon.
ICON_SIZE = {
    "fsx_ontap": 80,
    "ec2": 80,
    "lambda": 80,
    "ecs": 80,
    "eks": 80,
    "athena": 80,
    "glue": 80,
    "emr": 80,
    "bedrock": 80,
    "transfer": 80,
    "cloudfront": 80,
    "ebs": 80,
    # The Kubernetes icons have no prescribed size; 48 matches the AWS resource icons they sit with.
    "k8s_pod": 48,
    "k8s_pv": 48,
    # The Trident logo is portrait (350x387); aspect=fixed fits it inside the square.
    "trident": 48,
    "vpc_endpoint": 48,
    "s3_access_point": 48,
}

# --- styles --------------------------------------------------------------------------------------

GROUP_POINTS = (
    "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],"
    "[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]]"
)

# The readability floor, enforced by `make diagram-fonts`. A label is displayed at the size it has
# after the image is scaled into the reader's column, so these two numbers and `Diagram.width` are
# one decision: at 16 the canvas may be about 1000px before the effective size drops under 14px.
# The old values were 11 and 12 on a 1220px canvas, which reached a reader at roughly 8px.
# Raising them without also rebuilding the layout only trades unreadable text for collided text.
FONT_BODY = 16
FONT_GROUP = 18


@dataclass(frozen=True)
class Palette:
    """Everything the theme changes. Icon variant included, so one lookup covers the whole switch."""

    variant: str
    background: str
    ink: str
    cloud_stroke: str
    region_stroke: str
    box_stroke: str
    frame_stroke: str


PALETTES = {
    "light": Palette(
        variant="Light",
        background="#FFFFFF",
        ink="#232F3E",
        cloud_stroke="#232F3E",
        region_stroke="#00A4A6",
        box_stroke="#232F3E",
        frame_stroke="#666666",
    ),
    "dark": Palette(
        variant="Dark",
        background="#232F3E",
        ink="#FFFFFF",
        cloud_stroke="#FFFFFF",
        region_stroke="#4DD2D4",
        box_stroke="#FFFFFF",
        frame_stroke="#B0B8C1",
    ),
}


def group_style(
    gr_icon: str, stroke: str, ink: str, dashed: bool, background: str
) -> str:
    return (
        f"{GROUP_POINTS};outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;"
        f"fontSize={FONT_GROUP};"
        f"fontStyle=1;fontColor={ink};shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr_icon};"
        f"strokeColor={stroke};fillColor=none;verticalAlign=top;align=left;spacingLeft=30;"
        # 30, the offset the AWS group shape uses to clear its own corner badge. Raised
        # past it, a boundary's title travels along the top edge and comes to rest beside
        # an icon that is merely inside the boundary, where it reads as that icon's label
        # while the icon's real label sits underneath -- two names, one of them wrong.
        # `tools/check_diagram_flow.py` fails the build above 30.
        # The title needs a background for the same reason an edge label does: it sits at the
        # top-left of the frame, and a boundary crossed by a vertical run has that run passing
        # straight through the words. `fillColor=none` keeps the frame transparent, so this paints
        # behind the text only.
        f"spacingTop=4;dashed={1 if dashed else 0};labelBackgroundColor={background};"
    )


def icon_style(data_uri: str, ink: str) -> str:
    return (
        "sketch=0;html=1;shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
        f"labelPosition=center;align=center;imageAspect=1;aspect=fixed;fontSize={FONT_BODY};"
        f"fontColor={ink};image={data_uri};"
    )


def box_style(stroke: str, ink: str) -> str:
    """A named resource with no official icon.

    Backups and recovery points have no icon in the AWS asset package that is not an AWS Backup
    mark, and this figure's main path is the FSx for ONTAP native copy. Borrowing the AWS Backup
    resource icon for it would attribute the native path to AWS Backup, which is the confusion the
    article exists to remove. A named box states the resource without claiming a service.
    """
    return (
        f"rounded=1;whiteSpace=wrap;html=1;strokeColor={stroke};fillColor=none;"
        f"fontColor={ink};fontSize={FONT_BODY};verticalAlign=middle;align=center;"
    )


def frame_style(stroke: str, ink: str) -> str:
    """A dashed grouping, used where an edge must arrive at a set of resources rather than at one.

    The restore creates a file system, an SVM and a volume. An edge landing on the file system icon
    alone would say the backup restores into an existing file system, which is the misreading the
    article corrects.
    """
    return (
        f"rounded=1;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor={stroke};"
        f"fillColor=none;fontColor={ink};fontSize={FONT_BODY};verticalAlign=top;align=center;"
        "spacingTop=8;"
    )


def note_style(stroke: str, ink: str) -> str:
    """A 補足 / Notes box: left-aligned, top-aligned, so ※ items read as a list.

    A notes box carries ※-marked items with a bold noun-phrase headline each, not prose. It is the
    one box whose text is meant to be read left to right as lines rather than centred as a caption,
    so it aligns left and to the top rather than inheriting `box_style`'s centring. No edge touches
    it: a note annotates the figure, it is not a step in the flow, so the direction gate never sees
    it.

    The corner radius is absolute. draw.io's default arc is a share of the shorter side, so a tall
    notes box grows a corner wide enough to run through the first letters of its heading.
    """
    return (
        f"rounded=1;absoluteArcSize=1;arcSize=24;whiteSpace=wrap;html=1;strokeColor={stroke};"
        f"fillColor=none;fontColor={ink};fontSize={FONT_BODY};verticalAlign=top;align=left;"
        "spacingLeft=10;spacingRight=10;spacingTop=8;"
    )


def edge_style(ink: str, background: str) -> str:
    """An edge and its label.

    `labelBackgroundColor` is set explicitly because draw.io's default is an opaque white plate
    behind every edge label. On the dark canvas that plate stays white while the text turns white
    with it, so each label renders as a blank rectangle — visible only in the exported PNG, which is
    why the standard says to look at the picture rather than trust a parse.
    """
    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=open;endFill=0;"
        f"strokeColor={ink};strokeWidth=1;fontSize={FONT_BODY};fontColor={ink};"
        f"labelBackgroundColor={background};"
    )


# --- labels --------------------------------------------------------------------------------------

# Product names stay English in both languages: they are identifiers, and the naming rule requires
# the official service name with its Amazon / AWS prefix. Prose is localized. A role word is not a
# label, so a role goes in a second line under the full service name.
LABELS: dict[str, dict[str, str]] = {
    "aws_cloud": {"ja": "AWS Cloud", "en": "AWS Cloud"},
    "aws_region": {"ja": "AWS リージョン", "en": "AWS Region"},
    # --- figure 1: containers reach the volume through an access point ---
    "f1_ecs": {
        "ja": "Amazon ECS<br>(AWS Fargate)",
        "en": "Amazon ECS<br>(AWS Fargate)",
    },
    "f1_eks": {
        "ja": "Amazon EKS<br>(AWS Fargate)",
        "en": "Amazon EKS<br>(AWS Fargate)",
    },
    "f1_endpoint": {
        "ja": "S3 Gateway<br>エンドポイント",
        "en": "S3 gateway<br>endpoint",
    },
    "f1_ap": {
        "ja": "S3 Access Points<br>(VPC origin)",
        "en": "S3 Access Points<br>(VPC origin)",
    },
    "f1_fsx": {
        "ja": "Amazon FSx for<br>NetApp ONTAP",
        "en": "Amazon FSx for<br>NetApp ONTAP",
    },
    "f1_ec2": {"ja": "Amazon EC2<br>(NFS / SMB)", "en": "Amazon EC2<br>(NFS / SMB)"},
    "f1_e_api": {"ja": "S3 API", "en": "S3 API"},
    "f1_e_nfs": {"ja": "NFS / SMB", "en": "NFS / SMB"},
    "f1_notes": {
        "ja": (
            "<b>補足</b><br>"
            "※1 <b>コンテナにファイルのマウントは無い</b><br>"
            "アプリが S3 SDK で、アクセスポイントの alias か ARN を指定して呼ぶ。"
            "AWS Fargate からは S3 Access Points 経由で使うと、Amazon ECS のドキュメントが書く。<br>"
            "※2 <b>VPC origin は VPC の外からの要求を拒否する</b><br>"
            "Amazon Athena や Amazon Bedrock などには Internet origin が要る(図 2、図 3)。"
            "origin は作成後に変更できない。<br>"
            "※3 <b>NFS / SMB のクライアントは従来どおり</b><br>"
            "アクセスポイントを付けても、ボリュームの NFS / SMB の動作は変わらない。<br>"
            "※4 <b>認証はコンテナ側の IAM ロール</b><br>"
            "Amazon ECS はタスクロール、Amazon EKS は IRSA。アクセスポイントは VPC の中に置くものではなく、"
            "VPC origin で受け付ける VPC を指定する。"
        ),
        "en": (
            "<b>Notes</b><br>"
            "*1 <b>Containers have no file mount</b><br>"
            "The app calls the S3 SDK with the access point alias or ARN. The Amazon ECS "
            "documentation says AWS Fargate uses FSx for ONTAP through S3 Access Points.<br>"
            "*2 <b>VPC origin refuses requests from outside the VPC</b><br>"
            "Services such as Amazon Athena and Amazon Bedrock need Internet origin "
            "(Figures 2 and 3). The origin cannot be changed after creation.<br>"
            "*3 <b>NFS / SMB clients are unchanged</b><br>"
            "Attaching an access point does not change how the volume behaves over NFS "
            "or SMB.<br>"
            "*4 <b>Authentication is the container's IAM role</b><br>"
            "Amazon ECS uses a task role and Amazon EKS uses IRSA. The access point is not "
            "placed inside the VPC; VPC origin names the VPC it accepts."
        ),
    },
    # --- figure 2: four gates and the origin choice ---
    "f2_g1": {
        "ja": "<b>① IAM</b><br>呼び出し側の ID ポリシーと<br>アクセスポイントのポリシー",
        "en": "<b>1. IAM</b><br>The caller's identity policy and<br>the access point policy",
    },
    "f2_g2": {
        "ja": "<b>② ネットワーク origin</b><br>VPC origin か Internet origin<br>作成後に変更できない",
        "en": (
            "<b>2. Network origin</b><br>VPC origin or Internet origin<br>"
            "It cannot be changed after creation"
        ),
    },
    "f2_g3": {
        "ja": "<b>③ ファイルシステムの ID</b><br>アクセスポイントに固定した<br>UNIX か Windows のユーザー 1 つ",
        "en": (
            "<b>3. File system identity</b><br>One UNIX or Windows user<br>"
            "fixed on the access point"
        ),
    },
    "f2_g4": {
        "ja": "<b>④ ボリュームの権限</b><br>モードビット、NFSv4 ACL、NTFS ACL を<br>この ID に対して評価する",
        "en": (
            "<b>4. Volume permissions</b><br>Mode bits, NFSv4 ACLs, or NTFS ACLs,<br>"
            "evaluated for that identity"
        ),
    },
    "f2_vpc": {
        "ja": (
            "<b>VPC origin</b><br>AWS Fargate の Amazon ECS と Amazon EKS、<br>"
            "VPC 内の Amazon EC2 と AWS Lambda<br>S3 の Gateway エンドポイントを通る"
        ),
        "en": (
            "<b>VPC origin</b><br>Amazon ECS and Amazon EKS on AWS Fargate,<br>"
            "Amazon EC2 and AWS Lambda in the VPC<br>Traffic goes through an S3 gateway endpoint"
        ),
    },
    "f2_internet": {
        "ja": (
            "<b>Internet origin</b><br>Amazon Athena、AWS Glue、<br>"
            "Amazon EMR Serverless、AWS Transfer Family、<br>Amazon Bedrock Knowledge Bases、<br>"
            "Amazon CloudFront、VPC 外の AWS Lambda<br>公開はされない: SigV4 が必須で、<br>"
            "Block Public Access は常に有効"
        ),
        "en": (
            "<b>Internet origin</b><br>Amazon Athena, AWS Glue,<br>Amazon EMR Serverless,<br>"
            "Amazon Bedrock Knowledge Bases,<br>AWS Transfer Family, Amazon CloudFront,<br>"
            "and AWS Lambda outside a VPC<br>Not public: SigV4 is required and<br>"
            "Block Public Access is always on"
        ),
    },
    "f2_notes": {
        "ja": (
            "<b>補足</b><br>"
            "※1 <b>origin は呼び出し元から逆算する</b><br>"
            "AWS Fargate とマネージドサービスの両方から同じボリュームを使うなら、<br>"
            "origin の違うアクセスポイントを分けて作る。<br>"
            "※2 <b>ID は 1 つで、要求者ごとの ACL は評価されない</b><br>"
            "ID が SVM で解決できないと、作成 API が成功したあとに FAILED になる(実測、2026-11-10)。<br>"
            "※3 <b>VPC origin は管理者権限でも VPC の外からは拒否する</b><br>"
            "管理者権限の IAM プリンシパルでも AccessDenied だった(実測、2026-11-10)。"
        ),
        "en": (
            "<b>Notes</b><br>"
            "*1 <b>Work back from the caller to the origin</b><br>"
            "To use one volume from AWS Fargate and from managed services, create separate "
            "access points with different origins.<br>"
            "*2 <b>One identity; per-requester ACLs are not evaluated</b><br>"
            "If the SVM cannot resolve the identity, the access point goes to FAILED after "
            "the create call succeeds (observed 2026-11-10).<br>"
            "*3 <b>VPC origin refuses calls from outside the VPC, even with administrator "
            "rights</b><br>"
            "An administrator IAM principal got AccessDenied (observed 2026-11-10)."
        ),
    },
    # --- figure 3: consumers by origin ---
    "f3_fsx": {
        "ja": "Amazon FSx for<br>NetApp ONTAP",
        "en": "Amazon FSx for<br>NetApp ONTAP",
    },
    "f3_ap_internet": {
        "ja": "S3 Access Points<br>(Internet origin)",
        "en": "S3 Access Points<br>(Internet origin)",
    },
    "f3_ap_vpc": {
        "ja": "S3 Access Points<br>(VPC origin)",
        "en": "S3 Access Points<br>(VPC origin)",
    },
    "f3_frame_internet": {
        "ja": "Internet origin で使うサービス",
        "en": "Services that need Internet origin",
    },
    "f3_frame_vpc": {
        "ja": "VPC origin で使うコンピュート",
        "en": "Compute that uses VPC origin",
    },
    "f3_athena": {"ja": "Amazon Athena", "en": "Amazon Athena"},
    "f3_glue": {"ja": "AWS Glue", "en": "AWS Glue"},
    "f3_emr": {
        "ja": "Amazon EMR<br>(Serverless)",
        "en": "Amazon EMR<br>(Serverless)",
    },
    "f3_bedrock": {
        "ja": "Amazon Bedrock<br>(Knowledge Bases)",
        "en": "Amazon Bedrock<br>(Knowledge Bases)",
    },
    "f3_transfer": {
        "ja": "AWS Transfer<br>Family",
        "en": "AWS Transfer<br>Family",
    },
    "f3_cloudfront": {"ja": "Amazon CloudFront", "en": "Amazon CloudFront"},
    "f3_lambda_out": {
        "ja": "AWS Lambda<br>(VPC 外)",
        "en": "AWS Lambda<br>(outside a VPC)",
    },
    "f3_ecs": {
        "ja": "Amazon ECS<br>(AWS Fargate)",
        "en": "Amazon ECS<br>(AWS Fargate)",
    },
    "f3_eks": {
        "ja": "Amazon EKS<br>(AWS Fargate)",
        "en": "Amazon EKS<br>(AWS Fargate)",
    },
    "f3_ec2": {"ja": "Amazon EC2", "en": "Amazon EC2"},
    "f3_lambda_in": {
        "ja": "AWS Lambda<br>(VPC 内)",
        "en": "AWS Lambda<br>(in a VPC)",
    },
    # --- figure 4: storage for pods isolated with Nitro Sandbox ---
    "f4_cluster": {
        "ja": "クラスタ(Kubernetes 1.36)",
        "en": "Cluster (Kubernetes 1.36)",
    },
    "f4_eks": {
        "ja": "Amazon EKS<br>(Auto Mode)",
        "en": "Amazon EKS<br>(Auto Mode)",
    },
    "f4_normal": {
        "ja": "通常の Pod<br>(2 本、別のノード)",
        "en": "Normal pods<br>(two, on different nodes)",
    },
    "f4_isolated": {
        "ja": "隔離 Pod<br>(isolated-sandbox)",
        "en": "Isolated pod<br>(isolated-sandbox)",
    },
    "f4_nfs_pv": {
        "ja": "PersistentVolume<br>(NFS、ReadWriteMany)",
        "en": "PersistentVolume<br>(NFS, ReadWriteMany)",
    },
    "f4_trident": {
        "ja": "NetApp Trident<br>(CSI ドライバ)",
        "en": "NetApp Trident<br>(CSI driver)",
    },
    "f4_e_provision": {"ja": "払い出し", "en": "Provisions"},
    "f4_ebs": {
        "ja": "Amazon EBS<br>(ReadWriteOncePod)",
        "en": "Amazon EBS<br>(ReadWriteOncePod)",
    },
    "f4_fsx": {
        "ja": "Amazon FSx for<br>NetApp ONTAP",
        "en": "Amazon FSx for<br>NetApp ONTAP",
    },
    "f4_e_ok": {"ja": "マウントできた", "en": "Mounted"},
    "f4_e_fail": {"ja": "マウント失敗 ※1", "en": "Mount failed *1"},
    "f4_e_nfs": {"ja": "NFS", "en": "NFS"},
    "f4_notes": {
        "ja": (
            "<b>補足</b><br>"
            "※1 <b>コンテナ作成の段階で失敗</b><br>"
            "failed to fulfil mount request: ... no such file or directory。"
            "約 6 分で再起動 5 回の CrashLoopBackOff。原因は切り分けていない。<br>"
            "※2 <b>観測の範囲</b><br>"
            "2026-11-10、ap-northeast-1、1 回の観測。Trident の EKS アドオン v26.6.2-eksbuild.1。"
            "iSCSI と NVMe/TCP のブロックボリュームは試していない。<br>"
            "※3 <b>ドキュメントの記載</b><br>"
            "Storage with Nitro Sandboxes が挙げるのは Amazon EBS、Amazon EFS、tmpfs を使う CSI ドライバなど。"
            "サードパーティの CSI ドライバの NFS には触れていない。<br>"
            "※4 <b>アイコン</b><br>"
            "Pod と PersistentVolume は Kubernetes コミュニティのアイコン(Apache-2.0)、"
            "Trident は NetApp/trident リポジトリのロゴ。"
            "AWS のアイコンパッケージに EKS Auto Mode 専用のアイコンは無いので、Amazon EKS のアイコンを使った。"
        ),
        "en": (
            "<b>Notes</b><br>"
            "*1 <b>Failed at container creation</b><br>"
            "failed to fulfil mount request: ... no such file or directory, then "
            "CrashLoopBackOff after 5 restarts in about 6 minutes. The cause was not isolated.<br>"
            "*2 <b>Scope of the observation</b><br>"
            "2026-11-10, ap-northeast-1, one observation. Trident EKS add-on "
            "v26.6.2-eksbuild.1. iSCSI and NVMe/TCP block volumes were not tried.<br>"
            "*3 <b>What the documentation lists</b><br>"
            "Storage with Nitro Sandboxes lists Amazon EBS, Amazon EFS, tmpfs-backed CSI "
            "drivers, and others. It does not mention NFS from third-party CSI drivers.<br>"
            "*4 <b>Icons</b><br>"
            "The pod and PersistentVolume icons are Kubernetes community icons (Apache-2.0); "
            "the Trident logo is from the NetApp/trident repository. The AWS icon package "
            "has no icon for EKS Auto Mode, so the Amazon EKS icon is used."
        ),
    },
    "f3_notes": {
        "ja": (
            "<b>補足</b><br>"
            "※1 <b>origin が分かれ目</b><br>"
            "マネージドサービスは Internet origin、VPC 内のコンピュートは VPC origin。"
            "origin は作成後に変更できない。<br>"
            "※2 <b>描いていないものは「非対応」ではない</b><br>"
            "AWS DataSync、AWS Backup、Amazon Macie、Amazon GuardDuty、AWS Storage Gateway などは、"
            "公開された記載を見つけられなかった。本文の表に調べた範囲を書いた。<br>"
            "※3 <b>根拠は行ごとに違う</b><br>"
            "AWS のドキュメント、本リポジトリや他のリポジトリでの実測、ベンダー公表の区別は本文の表にある。"
        ),
        "en": (
            "<b>Notes</b><br>"
            "*1 <b>Origin is the dividing line</b><br>"
            "Managed services need Internet origin; compute inside a VPC uses VPC origin. "
            "The origin cannot be changed after creation.<br>"
            "*2 <b>What is not drawn is not \"unsupported\"</b><br>"
            "AWS DataSync, AWS Backup, Amazon Macie, Amazon GuardDuty, AWS Storage Gateway "
            "and others: no public statement was found. The table in the text lists what "
            "was searched.<br>"
            "*3 <b>The basis differs per row</b><br>"
            "The table in the text separates AWS documentation, measurements in this and "
            "other repositories, and vendor-published statements."
        ),
    },
}

CJK = re.compile(r"[\u3000-\u30ff\u4e00-\u9fff]")


def label(key: str, lang: str) -> str:
    """Look up a label, refusing to emit Japanese into an English diagram.

    A missing English string is otherwise invisible: the file exports, and the Japanese text simply
    sits in the English figure.
    """
    if key not in LABELS:
        raise SystemExit(f"build_diagrams: no label {key!r}")
    text = LABELS[key][lang]
    if lang != "ja" and CJK.search(text):
        raise SystemExit(
            f"build_diagrams: label {key!r} for {lang!r} contains Japanese"
        )
    return text


# --- spec ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    cid: str
    icon: str
    label: str
    x: int
    y: int


@dataclass(frozen=True)
class Group:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int
    gr_icon: str = "group_aws_cloud"
    kind: str = "cloud"
    dashed: bool = False


@dataclass(frozen=True)
class Box:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Note:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Frame:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Edge:
    cid: str
    source: str
    target: str
    label: str = ""
    exit_at: tuple[float, float] | None = None
    entry_at: tuple[float, float] | None = None
    # Where the label sits: position along the path (-1..1, 0 = midpoint) and a pixel nudge. The
    # default midpoint is frequently on top of an icon or another label, and a label is now wide
    # enough that it happens more often than it did at 11px.
    label_at: float | None = None
    label_offset: tuple[int, int] | None = None

    def style(self, ink: str, background: str) -> str:
        style = edge_style(ink, background)
        if self.exit_at:
            style += (
                f"exitX={self.exit_at[0]};exitY={self.exit_at[1]};exitDx=0;exitDy=0;"
            )
        if self.entry_at:
            style += f"entryX={self.entry_at[0]};entryY={self.entry_at[1]};entryDx=0;entryDy=0;"
        return style

    def geometry(self) -> list[str]:
        if self.label_at is None and self.label_offset is None:
            return ['          <mxGeometry relative="1" as="geometry" />']
        x = "" if self.label_at is None else f'x="{self.label_at}" '
        dx, dy = self.label_offset or (0, 0)
        return [
            f'          <mxGeometry {x}relative="1" as="geometry">',
            f'            <mxPoint as="offset" x="{dx}" y="{dy}" />',
            "          </mxGeometry>",
        ]


@dataclass(frozen=True)
class Diagram:
    name: str
    diagram_id: str
    width: int
    height: int
    groups: tuple[Group, ...] = ()
    frames: tuple[Frame, ...] = ()
    boxes: tuple[Box, ...] = ()
    notes: tuple[Note, ...] = ()
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()

    def filename(self, lang: str, theme: str) -> str:
        parts = [self.name]
        if lang != "ja":
            parts.append(lang)
        if theme != "light":
            parts.append(theme)
        return "-".join(parts) + ".drawio"


def _overview() -> Diagram:
    """Containers reach a volume through an access point, and file clients keep their path.

    The figure answers one question a reader brings from the file-mount picture: where did the
    mount go. There is none. The container calls the S3 API, the call crosses a gateway endpoint
    inside the VPC, the access point authorizes it, and the volume is the same one an NFS / SMB
    client mounts. The NFS / SMB client is drawn level with the volume rather than above it so its
    edge advances rightwards instead of climbing.

    Both container icons leave from their right side and land on the endpoint, one from above and
    one from the left, because the label sits under every icon and an edge leaving the bottom
    would run through the words.
    """
    return Diagram(
        name="s3ap-container-overview",
        diagram_id="s3ap-container-overview",
        width=940,
        height=920,
        groups=(
            Group("aws_cloud", "aws_cloud", 20, 20, 900, 880),
            Group(
                "region",
                "aws_region",
                40,
                60,
                860,
                530,
                gr_icon="group_region",
                kind="region",
                dashed=True,
            ),
        ),
        notes=(Note("notes", "f1_notes", 40, 620, 860, 260),),
        nodes=(
            Node("ecs", "ecs", "f1_ecs", 70, 110),
            Node("eks", "eks", "f1_eks", 70, 280),
            Node("endpoint", "vpc_endpoint", "f1_endpoint", 300, 296),
            Node("ap", "s3_access_point", "f1_ap", 470, 296),
            Node("fsx", "fsx_ontap", "f1_fsx", 650, 450),
            Node("ec2", "ec2", "f1_ec2", 440, 450),
        ),
        edges=(
            Edge(
                "e1",
                "ecs",
                "endpoint",
                "f1_e_api",
                exit_at=(1.0, 0.5),
                entry_at=(0.5, 0.0),
                label_offset=(0, -14),
            ),
            Edge(
                "e2",
                "eks",
                "endpoint",
                "f1_e_api",
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.5),
                label_offset=(0, -14),
            ),
            Edge(
                "e3",
                "endpoint",
                "ap",
                "f1_e_api",
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.5),
                label_offset=(0, -14),
            ),
            Edge(
                "e4",
                "ap",
                "fsx",
                exit_at=(1.0, 0.5),
                entry_at=(0.5, 0.0),
            ),
            Edge(
                "e5",
                "ec2",
                "fsx",
                "f1_e_nfs",
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.5),
                label_offset=(0, -14),
            ),
        ),
    )


def _request_path() -> Diagram:
    """The four gates a request passes, and why the origin splits the callers in two.

    The gates read downwards as the request meets them. The origin gate is the one with a branch,
    because it is the only gate whose setting cannot be changed afterwards and the one that decides
    which callers can reach the access point at all. The two outcomes sit to its right, both below
    the gate's centre so neither edge climbs.
    """
    return Diagram(
        name="s3ap-request-path",
        diagram_id="s3ap-request-path",
        width=940,
        height=860,
        boxes=(
            Box("g1", "f2_g1", 40, 40, 420, 90),
            Box("g2", "f2_g2", 40, 190, 420, 90),
            Box("g3", "f2_g3", 40, 340, 420, 90),
            Box("g4", "f2_g4", 40, 490, 420, 90),
            Box("vpc", "f2_vpc", 500, 250, 400, 120),
            Box("internet", "f2_internet", 500, 410, 400, 200),
        ),
        notes=(Note("notes", "f2_notes", 40, 640, 860, 200),),
        edges=(
            Edge("e1", "g1", "g2", exit_at=(0.5, 1.0), entry_at=(0.5, 0.0)),
            Edge("e2", "g2", "g3", exit_at=(0.5, 1.0), entry_at=(0.5, 0.0)),
            Edge("e3", "g3", "g4", exit_at=(0.5, 1.0), entry_at=(0.5, 0.0)),
            Edge("e4", "g2", "vpc", exit_at=(1.0, 0.5), entry_at=(0.0, 0.5)),
            Edge("e5", "g2", "internet", exit_at=(1.0, 0.5), entry_at=(0.0, 0.5)),
        ),
    )


def _consumer_map() -> Diagram:
    """Which AWS services use an access point, grouped by the origin they need.

    One edge goes to each frame rather than one to every service: the frame is the set the edge
    arrives at, and eight fans from a single icon would be unreadable. Quick, SageMaker and the
    services with no public statement are left out on purpose; the text lists them with what was
    searched, because absence from a figure reads as "unsupported" and that is not what was found.
    """
    return Diagram(
        name="s3ap-consumer-map",
        diagram_id="s3ap-consumer-map",
        width=980,
        height=870,
        groups=(Group("aws_cloud", "aws_cloud", 10, 10, 960, 850),),
        frames=(
            Frame("frame_internet", "f3_frame_internet", 340, 40, 620, 340),
            Frame("frame_vpc", "f3_frame_vpc", 340, 420, 620, 190),
        ),
        notes=(Note("notes", "f3_notes", 30, 640, 920, 200),),
        nodes=(
            Node("fsx", "fsx_ontap", "f3_fsx", 50, 60),
            Node("ap_internet", "s3_access_point", "f3_ap_internet", 240, 186),
            Node("ap_vpc", "s3_access_point", "f3_ap_vpc", 240, 491),
            Node("athena", "athena", "f3_athena", 360, 95),
            Node("glue", "glue", "f3_glue", 510, 95),
            Node("emr", "emr", "f3_emr", 660, 95),
            Node("bedrock", "bedrock", "f3_bedrock", 810, 95),
            Node("transfer", "transfer", "f3_transfer", 360, 235),
            Node("cloudfront", "cloudfront", "f3_cloudfront", 510, 235),
            Node("lambda_out", "lambda", "f3_lambda_out", 660, 235),
            Node("ecs", "ecs", "f3_ecs", 360, 475),
            Node("eks", "eks", "f3_eks", 510, 475),
            Node("ec2", "ec2", "f3_ec2", 660, 475),
            Node("lambda_in", "lambda", "f3_lambda_in", 810, 475),
        ),
        edges=(
            Edge(
                "e1",
                "fsx",
                "ap_internet",
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.5),
            ),
            Edge(
                "e2",
                "fsx",
                "ap_vpc",
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.5),
            ),
            Edge(
                "e3",
                "ap_internet",
                "frame_internet",
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.5),
            ),
            Edge(
                "e4",
                "ap_vpc",
                "frame_vpc",
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.5),
            ),
        ),
    )


def _sandbox_storage() -> Diagram:
    """What an isolated pod could mount, next to what normal pods could.

    One observation: the Trident NFS volume that two normal pods mounted failed in a pod run with
    `isolated-sandbox`, while an EBS volume mounted in that pod. Colour may not carry the failure
    (single-colour arrows), so the edge label says it and the note gives the error text.

    Every label sits under its icon, so no edge may leave an icon downwards: it would run through
    the words. Each edge leaves from the right and turns down onto its target's top, and the icons
    are staggered so that those horizontal runs cross nothing. The normal pods sit lower than the
    isolated pod for that reason, not because they come later. FSx for ONTAP sits outside the
    cluster frame because it is outside the cluster, and far enough right that the line down to it
    clears the two-line label under the PersistentVolume.
    """
    return Diagram(
        name="s3ap-sandbox-storage",
        diagram_id="s3ap-sandbox-storage",
        width=900,
        height=1110,
        groups=(Group("aws_cloud", "aws_cloud", 20, 20, 860, 1070),),
        frames=(Frame("cluster", "f4_cluster", 40, 70, 820, 470),),
        notes=(Note("notes", "f4_notes", 40, 735, 820, 335),),
        nodes=(
            Node("eks", "eks", "f4_eks", 70, 110),
            Node("isolated", "k8s_pod", "f4_isolated", 330, 130),
            Node("normal", "k8s_pod", "f4_normal", 150, 300),
            Node("ebs", "ebs", "f4_ebs", 720, 260),
            Node("trident", "trident", "f4_trident", 330, 420),
            Node("nfs_pv", "k8s_pv", "f4_nfs_pv", 540, 420),
            Node("fsx", "fsx_ontap", "f4_fsx", 740, 590),
        ),
        edges=(
            Edge(
                "e1",
                "normal",
                "nfs_pv",
                "f4_e_ok",
                exit_at=(1.0, 0.5),
                entry_at=(0.25, 0.0),
                label_at=-0.3,
                label_offset=(0, -14),
            ),
            Edge(
                "e2",
                "isolated",
                "nfs_pv",
                "f4_e_fail",
                exit_at=(1.0, 0.75),
                entry_at=(0.75, 0.0),
                label_at=-0.45,
                label_offset=(0, 16),
            ),
            Edge(
                "e3",
                "isolated",
                "ebs",
                "f4_e_ok",
                exit_at=(1.0, 0.25),
                entry_at=(0.5, 0.0),
                label_at=-0.2,
                label_offset=(0, -14),
            ),
            Edge(
                "e5",
                "trident",
                "nfs_pv",
                "f4_e_provision",
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.5),
                label_offset=(0, -14),
            ),
            Edge(
                "e4",
                "nfs_pv",
                "fsx",
                "f4_e_nfs",
                exit_at=(1.0, 0.5),
                entry_at=(0.5, 0.0),
                label_at=0.45,
                label_offset=(26, 0),
            ),
        ),
    )


DIAGRAMS = (
    _overview(),
    _request_path(),
    _consumer_map(),
    _sandbox_storage(),
)

# --- rendering -----------------------------------------------------------------------------------


def icon_package(explicit: str | None) -> Path:
    """Locate the AWS Architecture Icons package."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_dir():
            raise SystemExit(f"build_diagrams: --icons {path} is not a directory")
        return path
    env = os.environ.get("AWS_ICON_PACKAGE")
    if env:
        return icon_package(env)
    for candidate in sorted(Path.home().glob("Downloads/Icon-package_*"), reverse=True):
        if candidate.is_dir():
            return candidate
    raise SystemExit(
        "build_diagrams: the AWS Architecture Icons package was not found.\n"
        "  Download the current quarterly release from "
        "https://aws.amazon.com/architecture/icons/ and either leave it in ~/Downloads or pass\n"
        "  --icons <path> / set AWS_ICON_PACKAGE. The package is never committed here, which is\n"
        "  why the generated .drawio files are."
    )


def package_date(package: Path) -> str:
    """Read the release date from a package root or an extracted service-icon directory."""
    match = re.search(
        r"(?:Icon-package_|Architecture-Service-Icons_)(\d{8})", package.name
    )
    if not match:
        for child in package.iterdir():
            match = re.search(r"Architecture-Service-Icons_(\d{8})", child.name)
            if match:
                break
    if not match:
        raise SystemExit(
            f"build_diagrams: cannot read a release date from {package!s}.\n"
            "  Expected an Icon-package_YYYYMMDD directory or extracted "
            "Architecture-Service-Icons_YYYYMMDD directory from "
            "https://aws.amazon.com/architecture/icons/"
        )
    return match.group(1)


def data_uris(package: Path) -> dict[tuple[str, str], str]:
    """Read every icon, per theme, and build its draw.io data URI.

    Keyed by (icon, theme) because the general resource icons ship a Light and a Dark file and the
    dark diagram has to carry the Dark bytes. Service icons have one file and are read twice; that
    costs nothing and keeps the lookup uniform.

    The comma-only URI form is required. `data:image/svg+xml;base64,` exports a broken-image
    placeholder rather than failing, so the export "succeeds" and only looking at the picture shows
    it.
    """
    uris: dict[tuple[str, str], str] = {}
    date = package_date(package)
    for theme in THEMES:
        variant = PALETTES[theme].variant
        for key, relative in ICONS.items():
            resolved = relative.format(d=date, v=variant)
            path = package / resolved
            if not path.is_file():
                raise SystemExit(f"build_diagrams: {resolved} missing from {package}")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            uris[(key, theme)] = f"data:image/svg+xml,{encoded}"
        for key, name in LOCAL_ICONS.items():
            path = LOCAL_ICON_DIR / name
            if not path.is_file():
                raise SystemExit(
                    f"build_diagrams: {name} not found at {path.relative_to(ROOT)}.\n"
                    "  It is a third-party mark and is deliberately not committed. Fetch it with:\n"
                    f"  curl -sSf -o {path.relative_to(ROOT)} {LOCAL_ICON_URLS[key]}"
                )
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            mime = MIME_BY_SUFFIX[path.suffix.lower()]
            uris[(key, theme)] = f"data:{mime},{encoded}"
    return uris


def render(
    diagram: Diagram, lang: str, theme: str, uris: dict[tuple[str, str], str]
) -> str:
    p = PALETTES[theme]
    suffix = "".join(
        part
        for part in (
            f"-{lang}" if lang != "ja" else "",
            f"-{theme}" if theme != "light" else "",
        )
    )
    name = f"{diagram.name}{suffix}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<mxfile host="app.diagrams.net" modified="{MODIFIED}" '
            'agent="build_diagrams.py" version="24.0.0" type="device">'
        ),
        f'  <diagram id="{diagram.diagram_id}{suffix}" name="{name}">',
        (
            '    <mxGraphModel dx="1422" dy="762" grid="1" gridSize="10" guides="1" '
            'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            f'pageWidth="{diagram.width}" pageHeight="{diagram.height}" '
            f'background="{p.background}" math="0" shadow="0">'
        ),
        "      <root>",
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
    ]

    def vertex(
        cid: str, value: str, style: str, x: int, y: int, w: int, h: int
    ) -> None:
        lines.append(
            f"        <mxCell id={quoteattr(cid)} value={quoteattr(value)} "
            f'style={quoteattr(style)} vertex="1" parent="1">'
        )
        lines.append(
            f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />'
        )
        lines.append("        </mxCell>")

    # Edges first, so a vertex paints over a line rather than under it. A group's title sits at
    # the top-left of its frame, and a boundary crossed by a vertical run had that run passing
    # straight through the words; with the edges emitted last, the title's background could not
    # help, because the line was painted after it. Nothing is lost by the swap: no edge in these
    # figures is routed through a filled box, and an edge crossing a frame border is two thin
    # lines of one colour meeting either way.
    for edge in diagram.edges:
        value = label(edge.label, lang) if edge.label else ""
        lines.append(
            f"        <mxCell id={quoteattr(edge.cid)} value={quoteattr(value)} "
            f'style={quoteattr(edge.style(p.ink, p.background))} edge="1" '
            f"source={quoteattr(edge.source)} "
            f'target={quoteattr(edge.target)} parent="1">'
        )
        lines += edge.geometry()
        lines.append("        </mxCell>")
    for group in diagram.groups:
        stroke = p.cloud_stroke if group.kind == "cloud" else p.region_stroke
        vertex(
            group.cid,
            label(group.label, lang),
            group_style(group.gr_icon, stroke, p.ink, group.dashed, p.background),
            group.x,
            group.y,
            group.width,
            group.height,
        )
    # Frames and boxes before nodes, so an icon draws on top of the container it sits in.
    for frame in diagram.frames:
        vertex(
            frame.cid,
            label(frame.label, lang),
            frame_style(p.frame_stroke, p.ink),
            frame.x,
            frame.y,
            frame.width,
            frame.height,
        )
    for box in diagram.boxes:
        vertex(
            box.cid,
            label(box.label, lang),
            box_style(p.box_stroke, p.ink),
            box.x,
            box.y,
            box.width,
            box.height,
        )
    for note in diagram.notes:
        vertex(
            note.cid,
            label(note.label, lang),
            note_style(p.box_stroke, p.ink),
            note.x,
            note.y,
            note.width,
            note.height,
        )
    for node in diagram.nodes:
        size = ICON_SIZE[node.icon]
        vertex(
            node.cid,
            label(node.label, lang),
            icon_style(uris[(node.icon, theme)], p.ink)
            + ("imageBackground=#FFFFFF;" if theme == "dark" and node.icon in PLATED_ICONS else ""),
            node.x,
            node.y,
            size,
            size,
        )

    lines += ["      </root>", "    </mxGraphModel>", "  </diagram>", "</mxfile>", ""]
    return "\n".join(lines)


# --- checking ------------------------------------------------------------------------------------


def cells(xml: str) -> list[tuple[str, str, str, str]]:
    """Reduce a document to what a reader sees, so formatting is not compared."""
    out = []
    for cell in ET.fromstring(xml).find(".//root").iter("mxCell"):
        geometry = cell.find("mxGeometry")
        geo = (
            " ".join(f"{k}={v}" for k, v in sorted(geometry.attrib.items()))
            if geometry is not None
            else ""
        )
        style = re.sub(
            r"image=data:image/svg\+xml,([A-Za-z0-9+/=]{16})[A-Za-z0-9+/=]*",
            r"image=<\1...>",
            cell.get("style") or "",
        )
        out.append((cell.get("id") or "", cell.get("value") or "", style, geo))
    return out


def check(uris: dict[tuple[str, str], str], diagrams: tuple[Diagram, ...]) -> int:
    problems = 0
    total = 0
    for diagram in diagrams:
        for lang in LANGS:
            for theme in THEMES:
                total += 1
                path = DIAGRAM_DIR / diagram.filename(lang, theme)
                if not path.is_file():
                    print(f"  missing   {path.relative_to(ROOT)}", file=sys.stderr)
                    problems += 1
                    continue
                want = cells(render(diagram, lang, theme, uris))
                got = cells(path.read_text(encoding="utf-8"))
                if want == got:
                    continue
                problems += 1
                print(f"  differs   {path.relative_to(ROOT)}", file=sys.stderr)
                for a, b in zip(want, got):
                    if a != b:
                        print(f"      spec: {a}", file=sys.stderr)
                        print(f"      file: {b}", file=sys.stderr)
                if len(want) != len(got):
                    print(
                        f"      cell count spec={len(want)} file={len(got)}",
                        file=sys.stderr,
                    )
    if problems:
        print(
            "\n  A generated diagram was edited by hand, or the spec moved without a regenerate.\n"
            "  Run: python3 tools/build_diagrams.py --write --export",
            file=sys.stderr,
        )
        return 1
    print(f"diagrams: {total} file(s) match the spec")
    return 0


# --- exporting -----------------------------------------------------------------------------------


# draw.io stamps a fresh random element id into every SVG export and uses it twice: as the root id
# and as the CSS selector for its adaptive-background rule. Left alone, re-exporting an unchanged
# diagram still rewrites every SVG, and the files that did not change bury the one that did — the
# same failure the fixed MODIFIED timestamp prevents in the .drawio files. The id only has to be
# unique within the document, so deriving it from the file name is enough.
SVG_RANDOM_ID = re.compile(r"ge-svg-[A-Za-z0-9_-]+")


def stabilize_svg(target: Path) -> None:
    text = target.read_text(encoding="utf-8")
    stabilized = SVG_RANDOM_ID.sub(f"ge-svg-{target.stem}", text)
    if stabilized != text:
        target.write_text(stabilized, encoding="utf-8")


def export(diagram: Diagram, lang: str, theme: str) -> None:
    source = DIAGRAM_DIR / diagram.filename(lang, theme)
    stem = source.stem
    if not DRAWIO_CLI.is_file():
        print(
            f"  draw.io CLI not found at {DRAWIO_CLI}; skipping export", file=sys.stderr
        )
        return
    runs = (
        # SVG for the repository: crawlers and screen readers can reach the text.
        (IMAGE_DIR / f"{stem}.svg", ["--format", "svg", "--embed-svg-images"]),
        # PNG at 2x for the blog posts, which do not render SVG reliably.
        (PNG_DIR / f"{stem}@2x.png", ["--format", "png", "--scale", "2"]),
    )
    for target, extra in runs:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                str(DRAWIO_CLI),
                "--export",
                "--border",
                "12",
                *extra,
                "--output",
                str(target),
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        if target.suffix == ".svg":
            stabilize_svg(target)
        print(f"  exported  {target.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="regenerate the .drawio files"
    )
    parser.add_argument("--export", action="store_true", help="also export SVG and PNG")
    parser.add_argument(
        "--check", action="store_true", help="compare committed files to the spec"
    )
    parser.add_argument("--icons", help="path to the AWS Architecture Icons package")
    parser.add_argument(
        "--only",
        action="append",
        metavar="NAME",
        help="build or check only the named diagram(s); repeatable",
    )
    args = parser.parse_args()

    if not (args.write or args.check):
        parser.error("give --write or --check")

    names = {d.name for d in DIAGRAMS}
    if args.only:
        unknown = sorted(set(args.only) - names)
        if unknown:
            parser.error(f"--only names no such diagram: {', '.join(unknown)}")
        selected = tuple(d for d in DIAGRAMS if d.name in set(args.only))
    else:
        selected = DIAGRAMS

    uris = data_uris(icon_package(args.icons))

    if args.check:
        return check(uris, selected)

    DIAGRAM_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for diagram in selected:
        for lang in LANGS:
            for theme in THEMES:
                path = DIAGRAM_DIR / diagram.filename(lang, theme)
                path.write_text(render(diagram, lang, theme, uris), encoding="utf-8")
                print(f"  wrote     {path.relative_to(ROOT)}")
                if args.export:
                    export(diagram, lang, theme)
    return 0


if __name__ == "__main__":
    sys.exit(main())
