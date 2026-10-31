# Cloudflare Pagesで無料公開する

更新日：2026年10月31日（日本時間）。この手順は、独自ドメインを購入せず、Cloudflare Pagesの `プロジェクト名.pages.dev` で公開する場合のものです。ドメイン登録画面ではなく、GitHubリポジトリを接続した「Set up builds and deployments」画面を使います。

## CMSとGitHubの役割

更新の流れは **Pages CMSで編集 → GitHubのmainへ保存 → Cloudflare Pagesがビルド・公開** です。

Pages CMSはGitHubの `.pages.yml`、`data/*.json`、`assets/images/` を編集するため、公開先をCloudflareへ移しても、同じリポジトリ・ブランチで継続利用できます。CMSの接続先は `yusukeracing/yusuke-official-website`、ブランチは `main` のままです。GitHubリポジトリを削除したり、記事・写真をCloudflareの管理画面へ移したりしません。

CloudflareのGitHub連携では対象リポジトリだけを選択します。今回の公開に、サイト内へ管理者用のパスワード・GitHubトークンを埋め込む必要はありません。Cloudflareのログイン操作・権限許可はアカウント所有者が行います。

## 作成画面へ入力する値

| 画面の項目 | 入力値 |
| --- | --- |
| Project name | `yusuke-official-website` |
| Production branch | `main` |
| Framework preset | `None` |
| Build command | `bash scripts/build_cloudflare.sh` |
| Build output directory | `dist` |
| Root directory（advanced） | 空欄。リポジトリ直下を使います。 |

**Build commandへコマンド、Build output directoryへ `dist` を入れます。** 出力先の欄へPythonやbashのコマンドを貼り付けません。公開対象はビルドで作られる `dist/` だけです。リポジトリ直下や `docs/` を公開先に指定しません。

「Environment variables（advanced）」で、Production環境へ次の値を追加します。

| Variable name | Value |
| --- | --- |
| `PYTHON_VERSION` | `3.12` |
| `SKIP_DEPENDENCY_INSTALL` | `1` |
| `SITE_URL` | `https://yusuke-official-website.pages.dev/` |

`SITE_URL` は公開用のURLで、秘密情報ではありません。プロジェクト名を変更した場合や、Cloudflareが別のURLを提示した場合は、その確定した**本番用の固定URL**を末尾 `/` 付きで指定します。デプロイごとに変わるハッシュ付きのプレビューURLを指定しません。`/yusuke-official-website/` のようなGitHub Pages用のパスは追加せず、HTTPSのルートURLを使います。今回はNode.js用の環境変数やCloudflare Functionsの設定は不要です。

Preview環境のビルドも使う場合は、Preview側にも同じ固定の`SITE_URL`を設定します。これにより検索向けURLを本番にそろえます。Cloudflareのプレビュー向けnoindexヘッダーは上書きしません。プレビューURL自体は通常公開されるので、秘密情報を入れません。

ビルドコマンドは必要な画像処理依存を仮想環境へインストールし、`scripts/build.py --cloudflare`による公開ファイルの生成と検証を行います。`SITE_URL`が未設定・不正な場合は公開準備を中断します。検証失敗を無視してソースHTMLだけを公開しません。

## 公開URLの扱い

Cloudflareの `SITE_URL` は、ビルド時にCMSの「公開URL」より優先されます。生成する公開用 `data/site.json`、canonical・OGP・サイトマップ・404ページ内の参照も、実際の公開先へそろえます。

移行準備中はCMSに保存されたGitHub PagesのURLを保持し、Cloudflareだけに `SITE_URL` を設定します。これにより、確認のために既存のGitHub Pagesの公開先設定を先に書き換える必要はありません。

Cloudflareで正常公開を確認した後、Pages CMSの「サイト設定・SNS」→「公開URL（末尾 /）」も確定した `https://プロジェクト名.pages.dev/` へそろえます。将来URLを変更するときは、CMSの公開URLとCloudflareの `SITE_URL` の両方を変更して再ビルドします。Cloudflareの環境変数が古いままだと、CMSだけを変えてもCloudflareの公開URLは変わりません。

Cloudflare Pagesは`profile.html`のようなURLを`/profile`へ転送するため、Cloudflare用ビルドではcanonical・OGPのページURL・サイトマップを拡張子なしのURLへそろえます。物理ファイルは従来どおりフラットなHTMLで生成し、既存の`.html`リンクもCloudflareの転送を通じて利用できます。GitHub Pages用の通常ビルドでは既存のURL形式を維持します。

Cloudflare用の`dist/_headers`も生成し、フレームへの埋め込み制限・MIME推測防止・参照元情報の制限と、内容ハッシュ付き配信用画像のキャッシュ方針を指定します。ヘッダーが実際に有効になったかはCloudflare公開後のレスポンスで確認します。ファイル生成だけで本番ヘッダーの検証済みとはしません。

## 最初のデプロイと確認

1. 入力値を確認して「Save and Deploy」を押します。
2. Cloudflareの対象プロジェクト → **Deployments** で、`main` の対象コミットが成功したことを確認します。失敗した場合はビルドログのエラーを確認します。
3. Cloudflareが表示した `https://プロジェクト名.pages.dev/` を開きます。初回は証明書の準備を含め、完了状態を確認してから再試行します。
4. 現在のCMS設定はメンテナンスONなので、案内画面が出ることを確認します。今回の準備ではその設定をOFFにしません。
5. 公開再開の準備が整ったら、CMSでメンテナンスをOFFにして保存し、そのコミットのCloudflareデプロイ成功後に通常画面を確認します。
6. トップ画像、活動報告一覧・詳細・写真、ギャラリー、スマホメニュー、SNS、Google FormsをPCとスマートフォンで確認します。存在しないURLでも404の画像・CSSが読み込めるか確認します。
7. CMSから確認用の記事を作成し、写真挿入、編集、写真変更、掲載OFF、削除のそれぞれについてGitHubの保存コミットとCloudflareへの公開反映を確認します。実際に行っていない操作を合格扱いにしません。

この資料は設定・操作手順です。Cloudflareアカウントへのログイン、実Cloudflareデプロイ、実CMS画面から公開までの一連の操作、Google Formsの実受信を実施済みとするものではありません。生成物のローカル検証結果と、実際の公開先への接続結果は区別します。

## 保存したのに変わらない場合

| 段階 | 確認すること |
| --- | --- |
| CMS保存 | 画面に保存エラーがないか。対象リポジトリとブランチが正しいか。 |
| GitHub保存 | `main`のコミット履歴に、記事・写真・設定の意図した差分があるか。 |
| Cloudflare起動 | 対象コミットのProductionデプロイが作られたか。GitHub連携が有効か。 |
| ビルド | ビルドログで依存インストール・生成・検証が成功したか。Build commandと出力先が逆になっていないか。 |
| 公開先 | `pages.dev`の正しいプロジェクトを見ているか。`SITE_URL`が確定URLと一致するか。 |
| 表示 | メンテナンスONで通常画面を隠していないか。公開完了後にページを再読み込みしたか。 |

Cloudflareへの移行後は、GitHub Actionsの検証成功だけではCloudflare公開成功を確認できません。公開反映はCloudflareの **Deployments** で確認します。保存コミットがない保存失敗、コミット後のビルド待ち、ビルド失敗、成功後の古い表示を分けます。CMSの再認証・API制限等については [CMS反映の診断](CMS_DIAGNOSIS.md) も参照してください。

## GitHub Pagesの整理

Cloudflareで動作を確認するまでは既存のGitHub Pagesを維持します。切り替えが完了したら、GitHubの **Settings → Secrets and variables → Actions → Variables → New repository variable** で、名前`PAGES_HOSTING`・値`cloudflare`を登録します。これは秘密情報ではなく、今回追加したワークフローの切り替え設定です。以後GitHub Actionsの静的検証は続きますが、GitHub Pages向けの成果物アップロードとデプロイは停止します。Cloudflareへ入れる環境変数とは別の、GitHub側のRepository variableです。

その後GitHubの **Settings → Pages** で旧サイトをUnpublishします。GitHub Pagesの公開停止だけで、将来の自動デプロイまで停止したと決めつけません。切り替え前にすでに実行中の古いデプロイが残っていないことも確認します。復帰が必要な場合は`PAGES_HOSTING`を削除するか`github-pages`へ戻し、復帰先の公開URLを確認してワークフローを実行します。

GitHubの **Settings → Pages → Build and deployment** も確認し、意図しないブランチ直下・`docs/`からの公開が残っていないか確認します。これらのアカウント設定は、この資料を追加しただけでは変わりません。GitHubリポジトリとPages CMSの接続は残します。

## 無料枠と公開範囲

- 無料のURLは `名前.pages.dev` です。`名前.dev` という独自ドメインの無料取得ではありません。
- 今回のHTML・CSS・JavaScript・画像の静的リクエストは、Cloudflare公式資料で無料・無制限と案内されています。同時接続人数や無停止を保証する意味ではありません。
- Freeプランの月500回はビルド回数です。閲覧500回という意味ではありません。CMSの保存で起動するビルドも関係します。
- Cloudflareで公開しても、公開GitHubのコード・原画像・JSON・履歴の閲覧範囲は変わりません。メンテナンスや記事の掲載OFFは、秘密の下書きやアクセス制限の機能ではありません。
- 写真・ロゴの掲載条件、実績・本人発言の根拠確認は公開先を変更しても必要です。[権利・掲載根拠の確認](RIGHTS_REVIEW.md)を参照してください。

公式資料（2026年10月31日確認）：[Git連携](https://developers.cloudflare.com/pages/get-started/git-integration/)、[ビルド設定](https://developers.cloudflare.com/pages/configuration/build-configuration/)、[利用制限](https://developers.cloudflare.com/pages/platform/limits/)、[静的リクエストの料金](https://developers.cloudflare.com/pages/functions/pricing/)。
