# 2026-11-16 CMS更新後のメンテナンス解除不具合

## 原因と再現

最新main `ccffa0f` を取得して確認。メンテナンス保存値は `false` だが、次の3点が公開処理を止める。

1. `0fc0f21` の新記事のslugが日本語・空白・記号を含む。ビルドは `news item 2: slug must be unique lowercase letters/numbers separated by hyphens` で停止。
2. 同記事は写真を選択しているが `imageAlt` が未入力。slugだけ直しても `thumbnail alternative text is required` で停止。
3. CMSが空のレース予定 `schedule` を省略して保存。記事修正後のビルドは生成できるが `check_site.py` が `data/races.json: schedule must be an array` で失敗する。

この状態ではOFFの新しい公開版が完成せず、直前に成功したメンテナンス表示が残り得る。実際のCloudflareデプロイログ・配信本文は今回取得できていないため、本番の失敗履歴そのものは未確認。公開URLへの取得はCONNECT 403で遮断された。

## 修正

- 新記事slugを `suzuka-final-round-2026` に修正。画像を確認し、ゼッケン29で走行する写真の代替テキストを追加。本文・タイトル・写真・公開日・掲載設定を保持。
- CMSのslug欄に対応する正規表現と日本語エラーメッセージを設定。写真の説明欄は選択時必須と明示。重複slugや写真説明の未入力は引き続きビルドでも検証する。
- ビルド時に省略・nullのレース予定／結果を空配列へ正規化。原本は変更しない。不正な型・要素は明示的に失敗させる。
- CMSのメンテナンスOFFを維持。

## 検証

Cloudflare形式の公開ビルドと静的検証、記事テスト、公開パイプラインテスト、メンテナンスの往復テストを実施。回帰テストは、不正記事があるとOFFにしても旧生成物が保持されること、記事修正後に通常TOPと記事詳細が生成されることを確認する。レース一覧の省略・null・不正型もテストする。

## 公開後の確認

mainへ修正を反映したコミットのCloudflare Productionデプロイ成功後、固定URL `https://yusuke-official-website.pages.dev/` を開く。`/data/publication.json` の `sourceCommit` が修正を含むコミットで、`maintenanceEnabled` が `false` になっていることを確認する。記事詳細は `/article-suzuka-final-round-2026`。過去の個別デプロイURLや専用 `/maintenance` は復旧の確認先にしない。
