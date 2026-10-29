# 公開・保守の手順

この文書は担当者が外部サービスで行う設定を説明します。GitHub、Cloudflare、Google、Pages CMS のアカウント設定や DNS は、このリポジトリによって変更されません。

## 1. 初回公開

1. 写真・SNS・フォーム・公開 URL などの `xxx` を確認する。未確定の戦績・大会・スポンサーを架空の内容で埋めない。
2. リポジトリのルートで `python3 scripts/build.py`、`python3 scripts/check_site.py dist` を実行する。
3. `dist/` をローカルの HTTP サーバーで確認する。スマートフォンでメニュー、ページ間移動、画像、SNS、問い合わせフォームを操作する。
4. Pull Request を作成し、`Validate and build` の成功と変更内容を確認して main にマージする。
5. GitHub の **Settings → Pages → Build and deployment → Source** で **GitHub Actions** を選ぶ。初回は管理者がこの設定を行う。
6. `.github/workflows/pages.yml` は main の更新または手動実行で、検証した `dist/` だけを GitHub Pages にデプロイする。Pull Request では検証のみ実行する。既存の別の Pages デプロイ方式は重複実行させない。
7. Pages に表示された本番 URL で確認し、**Enforce HTTPS** を有効にする。独自ドメインでは証明書発行に時間がかかる場合がある。

ワークフロー内の外部 Action は公式 `actions` の完全なコミット SHA で固定しています。更新時は公式リリースと SHA を照合し、Pull Request で確認します。ビルド側の権限は `contents: read`、公開ジョブだけに `pages: write` と `id-token: write` を付与しています。

公開ジョブには `github-pages` Environment を使います。必要に応じて GitHub の Environment protection rules で承認者と公開可能なブランチを限定してください。実際に必要な承認機能は GitHub のプランに依存します。

## 2. URL・SEO・Search Console

`data/site.json` の `url` は末尾 `/` まで含む正しい HTTPS URL にします。初期値はプロジェクト Pages の URL です。独自ドメインが決まったら変更し、再ビルドして canonical・OGP・sitemap の整合性を確認します。404 とメンテナンスページは検索結果に登録しません。

Search Console でドメインまたは URL プレフィックスの所有権を確認し、公開後の `sitemap.xml` を送信します。ドメイン方式は DNS TXT レコードで検証できます。HTML 方式の場合は指定された確認ファイル等を公開対象に含める対応が別途必要です。Search Console の登録やインデックス反映は自動的には行われません。

OGP 用画像も本人・撮影者の許可を得た実画像に差し替え、共有先のデバッガー等でプレビューを確認します。

## 3. 写真の差し替え

提供されていない写真の場所には、写真の代わりに中立的な `xxx` 表示を使っています。架空のライダー写真、レース写真、スポンサーのロゴは含みません。

1. Pages CMS の Media から `assets/images/uploads/` に実画像をアップロードする。
2. 該当コンテンツの画像フィールドを、アップロードした画像のパスに変更する。
3. `xxx` を含むパスは未設定の目印として扱うため、`xxx-hero-01.webp` のような仮名のまま実画像を上書きせず、`uploads/hero-2026.webp` 等の実名へ変更する。
4. 主な差し替え位置は HERO、現在のシーズン、プロフィール、フォトストーリー、ギャラリー、ニュース、スポンサー。HTML の `PHOTO SLOT` コメントと JSON の画像フィールドを照合する。
5. モバイル用画像フィールドがある場合は縮小版を設定する。画像ごとに被写体を説明する代替テキストを記入する。
6. 実画像を設定した後、縦横比、トリミング、HERO の文字との重なり、スマートフォンでの見え方を確認する。

HERO は優先読み込み、それ以外は遅延読み込みを使います。画像を増やした後はブラウザの Network で、最初の画面でギャラリー全画像が取得されていないことを確認します。

## 4. Google Forms と Google Sheets

1. 所有者が Google Forms を作成する。項目例：お問い合わせ種類（スポンサー、取材・メディア、イベント、応援、その他）、氏名、会社名、メールアドレス、電話番号、本文。
2. 収集目的・保存期間・問い合わせ先など、必要な個人情報の案内をフォームに掲載する。不要な情報を必須にしない。
3. 送信／公開メニューから、サイト訪問者が回答できる範囲に設定する。組織内限定・ログイン必須になっていないか、別のブラウザでも確認する。
4. 埋め込み URL を取得して `data/site.json` の `googleFormUrl` に設定する。形式は `https://docs.google.com/forms/d/e/xxx/viewform?embedded=true` など。短縮 URL や管理・編集 URL は指定しない。
5. 回答タブで必要に応じて Google Sheets と連携する。通知・閲覧者は必要最小限にし、回答シートを公開しない。
6. 本番のお問い合わせページからテスト送信し、Forms または Sheets に届いたことを確認する。テスト回答は整理する。

フォームの表示・送信は Google Forms が担当し、サイト側では個人情報を保存しません。未設定時は `xxx` の案内となり、送信可能な偽フォームは表示しません。Google 側のサービス障害や回答受付停止は、サイト側だけでは解消できません。

## 5. GA4 と計測確認

GA4 の Web ストリームを作成して測定 ID（`G-…`）を `data/site.json` の `ga4Id` に設定します。初期値 `xxx` の間は GA4 通信を行いません。公開前にプライバシー告知、Google Analytics の利用案内、対象地域で必要な同意対応を確認してください。

公開後は GA4 のリアルタイム／DebugView とブラウザの Network で、ページビュー、スポンサー導線、支援導線、SNS、問い合わせ導線を確認します。サイト内クリックの計測はフォーム送信完了の保証ではありません。Google Forms の送信結果は Forms 側で確認してください。

測定 ID は公開前提の識別子です。API シークレット、サービスアカウント鍵、Google のパスワードは HTML・JavaScript・JSON に書きません。

## 6. GitHub・CMS のアクセス保護

- GitHub、ドメイン管理、Cloudflare、Google、Pages CMS へのログインに 2FA を設定し、可能ならパスキーまたはセキュリティキーを使用する。復旧コードはリポジトリ以外へ安全に保管する。
- Collaborators、GitHub Apps、OAuth Apps、Deploy Keys、SSH Keys、Personal Access Tokens の利用者と権限を定期確認する。不要な権限と退任した担当者のアクセスを削除する。
- main の Ruleset / Branch Protection で Pull Request と `Validate and build` の成功を必須にし、force push とブランチ削除を禁止する。必要ならレビュー必須・バイパス制限・署名付きコミットを追加する。
- 署名付きコミットを必須にする場合、CMS が作成するコミットも通せるか先にテストする。単にルールを追加して更新経路を止めない。
- Pages CMS は対象リポジトリにだけアクセスを許可する。本人が直接更新する場合は `main` を選び、フォーム保存 → 自動検証・公開とする。複数人での運用やPR必須の場合は `content` 等の編集ブランチを選び、Pull Request → レビュー → main → デプロイの順に公開する。
- CMS で使うブランチは CMS 側で選択する。`.pages.yml` だけでブランチや GitHub の権限が設定されるわけではない。具体的な操作は [CMS の使い方](CMS.md) を参照する。

これらの保護は外部アカウントの設定です。ファイルの実装と、実際の有効化・動作確認を区別して管理してください。

## 7. 独自ドメインと Cloudflare

独自ドメインを使用する場合のみ、必要に応じて `利用者 → Cloudflare → GitHub Pages` の構成にします。GitHub Pages 側の Custom domain とドメイン検証を設定したうえで、GitHub の最新の公式案内に従って必要な DNS レコードだけを登録します。DNS の値はここで推測しません。不要な古いレコードを残さず、証明書と HTTPS の動作を確認します。

ドメイン管理アカウントは権限を限定し、Registrar Lock を有効にします。Cloudflare を導入する場合は、利用プランに応じて WAF、DDoS 保護、Security Analytics、必要なレート制限を設定します。通常の訪問者や検索クローラーを誤って遮断していないか確認します。Hotlink Protection は画像表示や SNS の共有画像を壊さない範囲で検討します。

キャッシュの運用目安：

| 対象 | 方針 |
| --- | --- |
| `assets/css/`、`assets/js/`、`assets/icons/` | 長めのキャッシュ。変更時は参照バージョンも更新し、必要に応じてパージする |
| `assets/images/` | 長めのキャッシュ。画像差し替え時は新しいファイル名を使用する |
| HTML、`data/*.json`、`sitemap.xml`、`robots.txt` | 更新反映を優先する。長期固定キャッシュを避ける |

GitHub Pages では任意のレスポンスヘッダーをリポジトリだけで設定できません。Cloudflare の Response Header Transform Rules 等で必要なヘッダーを設定します。

```text
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

HSTS は HTTPS が全対象で安定稼働した後に導入します。`includeSubDomains` や preload は他のサブドメインへの影響を確認してから判断してください。

サイトは HTML の CSP meta で接続先を制限しています。Cloudflare にも CSP を追加する場合、複数ポリシーは両方の制限が適用されるため、既存ポリシーと整合させます。初めは `Content-Security-Policy-Report-Only` で実機確認してから強制する方法もあります。

主な許可先：同一オリジンの CSS・JavaScript・画像・JSON、Google Forms の `https://docs.google.com`、GA4 の `https://www.googletagmanager.com` と Analytics の計測先。`object-src 'none'`、`base-uri 'self'` を維持します。JSON-LD の静的インラインブロックには SHA-256 を使います。ヘッダーをコピーする場合も、各 HTML の JSON-LD の内容に対応するハッシュを維持し、広い `unsafe-inline` で回避しないでください。外部 CDN の追加は不要です。

CSP の導入・変更後は、Console の違反、画像、Google Forms、GA4、モバイルメニュー、ギャラリーを必ず確認します。Cloudflare のルール・証明書・権限・DNS の設定は、このコードを配置しただけでは有効になりません。

## 8. 404 と計画メンテナンス

サーバーを止めずに案内を表示するには、Pages CMSの「サイト設定・SNS」で **「メンテナンス画面を表示する」をON**にして保存します。必要に応じて「メンテナンス中の案内文」を変更します。`main` の公開処理が完了すると、TOP・各ページへの直接アクセス・存在しないURLの404案内が同じメンテナンス画面になります。通常運用はOFFです。

コードで管理する場合の設定先は `data/site.json` です。

```json
{
  "maintenanceEnabled": true,
  "maintenanceMessage": "現在、サイトを更新しています。公開再開までしばらくお待ちください。"
}
```

上記は変更する2項目の抜粋です。ファイル全体をこの内容に置き換えず、既存項目を残してください。`true` / `false` は引用符なしの真偽値です。ビルドは文字列の `"false"` などをエラーにします。

ビルドはソースのHTMLを保持したまま、公開用 `dist/` の全11HTMLをメンテナンス案内に置き換えます。JavaScriptのリダイレクトではないため、JavaScript無効時や直接のページURLでも表示されます。メインメニューを除去し、本人SNSへのリンクは利用できます。案内文はHTMLとして実行せず文字として表示します。

再開は同じ設定を **OFF / `false`** にして保存・再公開します。通常HTMLを消したり、Gitを巻き戻したり、`404.html` を元に戻したりする必要はありません。公開処理が失敗すると直前の公開版が続くため、GitHub Actionsの成功を確認してください。

`404.html` は通常、存在しないURLに対してだけGitHub Pagesが返すページです。内容を手動で変える場合はこのファイルを編集しますが、変更だけでサイト全体は切り替わりません。メンテナンス中も既存URLはHTTP 200、存在しないURLはHTTP 404です。GitHub Pagesではリポジトリのこの設定からHTTP 503や `Retry-After` を返せません。全ページを `noindex` とし、サイトマップを空にして一時的な案内を検索に登録させない構成です。クローラーによる `noindex` の読み取りは許可します。解除後に通常の検索設定と9ページのサイトマップを復元します。

この切り替えは次の公開完了時に反映され、すでに表示中のページや外部キャッシュを即時消去する機能ではありません。公開JSON・画像を非公開にするアクセス制限でもありません。GitHub Pages自体が停止している場合は案内も表示できません。長時間の停止でHTTP 503が必要な場合は、独自ドメインのプロキシ等での対応を別途検討します。

## 9. 動作・速度の確認

初期チェックに加え、写真と外部サービスを設定した本番相当の状態で検証します。

- 画面幅 320、375、390、430、768、1024、1366、1440、1920px で横スクロール・文字切れ・画像の構図を確認する。
- キーボードでメニュー・リンク・Lightbox を操作する。フォーカス表示、Esc での終了、終了後のフォーカス復帰、OS の動きを減らす設定を確認する。
- Lighthouse で Performance、Accessibility、Best Practices、SEO を確認する。本番公開後は PageSpeed Insights でも測定する。
- LCP、CLS、INP、画像容量、Render Blocking を確認する。実際の写真やフォームが未設定の段階の数値を、本番の保証として扱わない。
- Network の初回読み込みで、不要なギャラリー写真・ニュース写真・巨大フォント・SNS タイムラインが取得されていないことを確認する。未設定の GA4 や Forms に通信しないことも確認する。
- 外部サービスは実アカウント・実 URL で操作し、設定があることと送信／計測が完了することを区別する。

## 10. 監視・バックアップ・復旧

定期的に GitHub の変更履歴・アカウントのログイン・Security、Cloudflare Security Events、Search Console、GA4 を確認します。見知らぬコミット、急なアクセス変化、DNS 変更、GitHub App の追加を調査します。

画像原本、掲載許可、プロフィール資料、スポンサー資料、戦績の根拠資料は GitHub 以外にもバックアップします。Forms / Sheets の回答はアクセス制限と保存方針に従って管理します。

改ざんが疑われる場合：

1. 変更履歴・ログを保存し、公開内容と変更箇所を確認する。
2. 不正アクセス経路を調べ、該当するキー・トークン・アプリ権限・ログインセッションを失効させる。秘密情報が流出した場合はファイルから消すだけで終わらせず、発行元で再発行する。
3. 正常と確認できるコミットと比較し、レビュー可能な復旧 Pull Request を作成する。公開ブランチの force push で履歴を消さない。
4. 検証後に再デプロイし、必要なら CDN キャッシュをパージする。
5. 本番ページ、検索向けメタデータ、外部リンク、Forms、GA4、DNS、権限を再確認する。

静的配信と最小依存は攻撃面を減らしますが、アカウント侵害や設定ミスまで防ぐ保証はありません。運用権限・変更確認・復旧可能な履歴を併せて管理してください。
