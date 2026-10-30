# 第三者の素材・ライブラリ

2026-10-30時点の構成です。サイト独自コードに、新たな第三者向け利用許諾を設定する文書ではありません。

| 対象 | 使用場所 | ライセンス・確認範囲 |
| --- | --- | --- |
| Pillow 13.0.0 | ビルド時の画像縮小・色プロファイル処理 | インストール済み配布物の License-Expression は MIT-CMU。配布物の [LICENSE](licenses/Pillow-LICENSE.txt) を保持。ライブラリ自体はWebへ配信しない。 |
| Simple Icons | Instagram/Facebook/Xのリンク用アイコン | プロジェクトのCC0-1.0と各ブランドの権利・利用ガイドは別。[アイコンの説明](assets/icons/README.md)、[確認表](docs/RIGHTS_REVIEW.md)を参照。 |
| Playwright 1.62.0 | 開発時のブラウザーテストのみ | Apache-2.0。[公式ライセンス](https://github.com/microsoft/playwright/blob/main/LICENSE)。ブラウザーバイナリ/テストライブラリ自体はWeb成果物・ソース納品へ同梱しない。 |
| OSのシステムフォント | CSSのfont-family指定 | フォントファイルを再配布しない。外部Webフォント通信も追加しない。 |
| 利用者提供の写真 | 原本と配信用画像 | 写真固有の撮影者・クレジット条件に従う。Pillowやサイトコードのライセンスで写真の権利が許諾されるわけではない。 |

ビルド依存の固定値は [requirements-build.txt](requirements-build.txt)。ブラウザーテストツールは任意の開発依存で、公開サイトの実行には不要です。
