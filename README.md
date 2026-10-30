# 池田優介 Racing Website

白とレーシングブルー、写真と余白を使った静的サイトです。公開サイトの実行にPHP・データベース・Node.jsは使いません。画像の配信用生成だけにPythonとPillowを使います。

## 現在の状態

- CMSはPages CMS、保存先はGitHub `main` の `data/*.json` です。
- GitHub Actionsが必要なファイルだけを `dist/` に生成し、GitHub Pagesへ公開します。`docs/` は説明資料で、サイトの公開フォルダではありません。
- 利用者がCMSで設定した **メンテナンスONを保持**しています。解除はCMSの「サイト設定・SNS」→「メンテナンス画面を表示する」をOFFにして保存します。
- 通常サイトは、設定を変更しない `--normal-preview` で別に確認できます。
- トップ画像の設定は `assets/images/yusuke.gallery_09.jpg` です。公開時はその写真から作った配信用WebPを使います。

原因・変更・テスト・未確認事項の入口は [今回の確認報告](docs/AUDIT_REPORT.md) です。

## 日常の更新

[Pages CMS](https://app.pagescms.org/)で対象リポジトリと `main` を選びます。

「活動報告・ニュース」で記事のタイトル・公開日・冒頭本文・サムネイルを入力できます。「本文の文章・写真」は項目を順に追加し、文章と複数写真を並べます。写真の説明と代替テキストも入力できます。保存後はGitHub Actionsの公開処理を確認します。

記事の「掲載する」をOFFにすると一覧・詳細・公開用JSON・サイトマップから外れます。ただし公開GitHubとその履歴を非公開にはしないため、個人情報・機密情報を含む下書きは保存しません。公開日は表示・並べ替え用で、予約公開の設定ではありません。

写真はCMSの `assets/images` で管理します。既存写真と `uploads/` サブフォルダを同じ画面で扱い、原本のパスはJSONへ相対パスで保存します。原本を置き換えずに配信用画像を自動生成するため、コードや配信用ファイルを手動で編集する必要はありません。

詳しくは [写真付き記事の操作手順](docs/CMS.md)、保存したのに変わらない場合は [反映不具合の切り分け](docs/CMS_DIAGNOSIS.md) を参照してください。

## ビルドと確認

Python 3.11以上が目安です。ビルド依存は固定版のPillowです。

```bash
python3 -m venv .build-venv
.build-venv/bin/python -m pip install -r requirements-build.txt
.build-venv/bin/python scripts/build.py
.build-venv/bin/python scripts/check_site.py dist
```

メンテナンス設定を維持したまま通常表示を確認する場合：

```bash
.build-venv/bin/python scripts/build.py --normal-preview --output dist-preview
.build-venv/bin/python scripts/check_site.py dist-preview
.build-venv/bin/python -m http.server 8000 --bind 127.0.0.1 --directory dist-preview
```

`file://`でのダブルクリック表示ではなくHTTPサーバーを使います。公開には `dist/` だけを使います。`dist-preview/` はメンテナンスを解除して作った確認用なので、現在の公開設定を維持する場合はデプロイしません。

## 元写真と配信用画像

- `assets/images/`：利用者提供の原本とCMSアップロード。元ファイルを改変せず保持します。
- `dist/assets/optimized/`：参照中の写真だけを自然比率で縮小し、向きを補正・sRGB化した配信用WebP。色の演出や切り抜きはしません。
- `dist/data/media-manifest.json`：原本SHA、寸法、変換条件、配信用SHA・容量。元写真との対応を確認できます。
- `dist/data/publication.json`：公開版ID、生成ページ一覧、メンテナンス状態。HTML・CSS・JS・JSONの版をそろえます。

原本の同一内容の別名は保存し、配信用画像はハッシュで共通化します。WebPは非可逆圧縮なので、原本と画素値が完全一致するという意味ではありません。

## テスト

Python標準ライブラリとビルド依存で実行するテスト：

```bash
.build-venv/bin/python scripts/test_news_content.py
.build-venv/bin/python scripts/test_publication_pipeline.py
.build-venv/bin/python scripts/test_maintenance.py
.build-venv/bin/python scripts/test_social_links.py
```

ブラウザー確認には開発用のPython PlaywrightとChromiumが別途必要です。公開サイトには同梱しません。

```bash
python3 scripts/test_release.py --directory dist-preview --report docs/release-browser-results.json
python3 scripts/test_photo_loading.py --directory dist-preview
```

実機、Safari、実CMSのログイン操作、Googleフォームの実受信、公開先の証明書やHTTPヘッダーは、ローカルの代替応答だけでは検証できません。[今回のテスト記録](docs/RELEASE_TESTS.md)で実施済みと未確認を区別します。

## 資料

| 内容 | 文書 |
| --- | --- |
| 総合報告・原因・公開判定 | [AUDIT_REPORT](docs/AUDIT_REPORT.md) |
| 写真付き記事の更新 | [CMS](docs/CMS.md) |
| CMS保存・反映の診断 | [CMS_DIAGNOSIS](docs/CMS_DIAGNOSIS.md) |
| 削除したファイルと保持理由 | [CLEANUP](docs/CLEANUP.md) |
| テスト結果・未実施 | [RELEASE_TESTS](docs/RELEASE_TESTS.md) |
| 権利・戦績・重複の確認 | [RIGHTS_REVIEW](docs/RIGHTS_REVIEW.md) |
| Web公開と公開GitHubの区分 | [PUBLICATION_BOUNDARY](docs/PUBLICATION_BOUNDARY.md) |
| セキュリティと依存 | [SECURITY](docs/SECURITY.md) |
| 公開・バックアップ・復旧 | [OPERATIONS](docs/OPERATIONS.md) |
| 改ざん発見時の記録様式 | [INCIDENT_RESPONSE](docs/INCIDENT_RESPONSE.md) |
| 第三者ライセンス | [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) |

資料をWeb成果物から除外しても、公開リポジトリからは読めます。秘密鍵、トークン、フォーム回答原文、非公開の連絡先や内部調査ログをGitへ保存しません。
