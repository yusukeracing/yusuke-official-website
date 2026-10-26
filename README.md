# 池田優介 Official Racing Website

全日本ロードレース選手権 ST600・池田優介選手の公式サイトです。白とレーシングブルーを中心に、写真・タイポグラフィ・余白で構成しています。

HTML / CSS / Vanilla JavaScript の静的サイトです。Node.js、PHP、データベース、フロントエンドフレームワークは不要です。

## ローカルで確認する

Python 3 が必要です。リポジトリのルートで実行します。

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

ブラウザでローカルサーバーの `index.html` を開きます。JSON を `fetch()` するため、HTML のダブルクリックによる `file://` 表示は使用しません。

検証・公開用ファイルの生成：

```bash
python3 scripts/build.py
python3 scripts/check_site.py dist
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist
```

`dist/` が公開対象です。ソース、運用資料、設定ファイルは読みやすい状態で保持します。ビルドは `data/site.json` の公開 URL を使って検索エンジン向けの URL も生成します。公開 URL を変えた場合は必ず再ビルドしてください。

## ページと編集するファイル

| ページ / 情報 | ファイル |
| --- | --- |
| トップ | `index.html` |
| プロフィール | `profile.html` / `data/profile.json` |
| レース・予定・戦績 | `race.html` / `data/races.json` |
| ニュース | `news.html` / `data/news.json` |
| 法人パートナー | `sponsor.html` / `data/sponsors.json` |
| 個人サポート | `support.html` |
| お問い合わせ | `contact.html` |
| 404 / 計画メンテナンス | `404.html` / `maintenance.html` |
| サイト設定・SNS・GA4・Google Forms | `data/site.json` |
| ギャラリー | `data/gallery.json` |
| CMS 設定 | `.pages.yml` |
| スタイル / 挙動 | `assets/css/` / `assets/js/` |

Pages CMS ではニュース・戦績・予定・プロフィール・スポンサー・写真・サイト設定を編集できます。接続と日常の更新は [CMS の使い方](docs/CMS.md)、公開・セキュリティ・障害対応は [運用手順](docs/OPERATIONS.md) を参照してください。

## 写真と未確定情報

提供された `yusuke.hero_01.jpg`〜`yusuke.hero_04.jpg` を、TOP・CURRENT SEASON・プロフィール・PHOTO STORYに登録しています。未提供の写真枠は `xxx` と `<!-- PHOTO SLOT : xxx-… -->` コメントで示しています。人物やレースの仮写真は生成・流用していません。戦績・スポンサー・ニュース・レース予定も未確認の内容を補完していません。

写真は HTML の `src` だけでなく、対応する JSON / Pages CMS の画像設定を更新してください。特に PHOTO STORY は JSON から再描画します。登録場所は [写真の差し替え](docs/CMS.md#写真の差し替え) の対応表を参照してください。

画像は Pages CMS から `assets/images/uploads/` にアップロードするか、JSON の画像パスを実際のファイル名に変更してください。ファイル名に `xxx` が含まれる画像は仮枠として扱い、読み込みません。`xxx` は本番データに置き換える目印です。写真の権利と選手・チーム・撮影者の掲載許可を確認してください。

推奨サイズ：PC は横幅 1600px 程度、タブレットは 1024px 程度、スマートフォンは 640〜800px 程度。WebP / AVIF を推奨し、HERO は 150〜300KB、通常写真は 80〜200KB、サムネイルは 30〜100KB を目安にします。`mobileImage` などの対応フィールドには縮小版を指定できます。元の 4K JPEG を直接掲載しないでください。

## 公開前に必要な設定

- 本人の写真、過去の戦績、2026 年の日程・結果、ニュース、スポンサーを、確認できた情報で登録する。
- `data/site.json` の `url` を公開 URL に合わせる。初期値は `https://yusukeracing.github.io/yusuke-official-website/`。
- SNS の `xxx` を実際のアカウントに変更する。
- Google Forms を作成し、`googleFormUrl` に埋め込み用 URL を設定する。必要に応じて公開可能なメール・電話番号、スポンサー資料 URL を設定する。
- GA4 を使う場合は `ga4Id` を実際の測定 ID に変更し、プライバシー告知・必要な同意対応を確認する。
- GitHub Pages と Pages CMS を接続し、編集権限、main の保護、HTTPS を設定する。
- 写真・フォーム・計測設定後に実機と Lighthouse / PageSpeed Insights で再検証する。

これらの外部サービスやアカウントの設定は、リポジトリ内のファイルを追加しただけでは有効になりません。秘密鍵・トークン・パスワード・`.env` はコミットしないでください。

## 写真とTOPボタンの回帰テスト（開発用・任意）

Python Playwright を使い、実画像の表示、キャッシュ済み画像の判定、モバイル画像がない場合の代替表示、TOPボタンのコントラストと重なりを確認できます。サイト本体や公開ビルドには Playwright は不要です。

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
python3 scripts/test_photo_loading.py
```

システムに Chromium がある場合はそれを使用します。公開用ファイルを確認するときは `python3 scripts/test_photo_loading.py --directory dist` を実行します。
