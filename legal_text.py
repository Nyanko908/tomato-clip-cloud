# -*- coding: utf-8 -*-
"""
legal_text.py - 利用規約・プライバシーポリシーの本文（実データ）

出典: C:\\Users\\koumo\\tomato-shorts-web\\src\\components\\Terms.jsx / PrivacyPolicy.jsx
本文は日本語・英語版のみ存在する（法的文書のため機械翻訳は行わない）。
"""

TERMS = {
    "ja": {
        "updated": "最終更新日：2026年7月4日",
        "sections": [
            ("1. サービス概要", "Tomato Clip は、AI を活用したショート動画の自動生成・投稿ソフトウェアです。本規約は、Tomato Clip の購入および使用に適用されます。"),
            ("2. ライセンス", "本ソフトウェアは買い切り（永続ライセンス）として提供されます。購入者は個人・商用目的で使用することができます。再販・再配布・逆コンパイルは禁止します。"),
            ("3. 禁止事項", "以下の行為を禁止します：第三者への無断配布、違法コンテンツの生成、著作権を侵害するコンテンツの作成、本ソフトウェアを利用した迷惑行為・スパム行為。"),
            ("4. 免責事項", "本ソフトウェアは現状有姿で提供されます。当方は、ソフトウェアの使用によって生じた損害・損失について、法律の定める範囲を超えて責任を負いません。生成されるコンテンツの内容についても、ユーザーが責任を負うものとします。"),
            ("5. 返金ポリシー", "デジタルコンテンツの性質上、購入完了後の返金は原則としてお受けできません。購入前に無料体験をご利用ください。"),
            ("6. 規約の変更", "当方は、本規約を予告なく変更する場合があります。変更後も本ソフトウェアを使用し続けることで、変更後の規約に同意したものとみなします。"),
            ("7. 準拠法", "本規約は日本法に準拠し、解釈されます。"),
        ],
    },
    "en": {
        "updated": "Last updated: July 4, 2026",
        "sections": [
            ("1. Overview", "Tomato Clip is an AI-powered software for automated short video generation and posting. These Terms apply to the purchase and use of Tomato Clip."),
            ("2. License", "This software is provided as a one-time purchase (perpetual license). Purchasers may use it for personal or commercial purposes. Resale, redistribution, and decompilation are prohibited."),
            ("3. Prohibited Activities", "The following are prohibited: unauthorized distribution to third parties, generation of illegal content, creation of copyright-infringing content, and use of the software for spam or harassment."),
            ("4. Disclaimer", 'This software is provided "as is." We are not liable for any damages or losses arising from use of the software beyond what is required by law. Users are responsible for the content they generate.'),
            ("5. Refund Policy", "Due to the nature of digital products, refunds are generally not available after purchase. Please use the free trial before purchasing."),
            ("6. Changes to Terms", "We may update these Terms without prior notice. Continued use of the software after changes constitutes acceptance of the updated Terms."),
            ("7. Governing Law", "These Terms are governed by and construed in accordance with the laws of Japan."),
        ],
    },
}

PRIVACY = {
    "ja": {
        "updated": "最終更新日：2026年7月4日",
        "sections": [
            ("1. 収集する情報", "Tomato Clip は、本ウェブサイト上で個人情報を直接収集しません。購入は Booth（pixiv 株式会社）を通じて行われ、購入に関する情報は Booth のプライバシーポリシーに従い管理されます。"),
            ("2. Gemini API の使用", "Tomato Clip は Google Gemini API を使用して動画コンテンツを生成します。ソフトウェアの使用中に送信されたデータは Google のプライバシーポリシーに従って処理されます。"),
            ("3. アクセス解析", "本サイトでは、Google Search Console を利用してアクセス状況を把握する場合があります。これらのツールは匿名の統計情報のみを収集します。"),
            ("4. 第三者への提供", "当方は、法律に基づく場合を除き、収集した情報を第三者に提供・販売・共有することはありません。"),
            ("5. お問い合わせ", "プライバシーに関するお問い合わせは、Booth のメッセージ機能よりご連絡ください。"),
        ],
    },
    "en": {
        "updated": "Last updated: July 4, 2026",
        "sections": [
            ("1. Information We Collect", "Tomato Clip does not directly collect personal information on this website. Purchases are processed through Booth (pixiv Inc.), and purchase-related information is managed under Booth's privacy policy."),
            ("2. Use of Gemini API", "Tomato Clip uses the Google Gemini API to generate video content. Data submitted during use of the software is processed in accordance with Google's privacy policy."),
            ("3. Analytics", "This site may use Google Search Console to understand site traffic. These tools collect only anonymized statistical information."),
            ("4. Third-Party Disclosure", "We do not sell, trade, or otherwise transfer your information to third parties, except as required by law."),
            ("5. Contact", "For privacy-related inquiries, please contact us via the Booth messaging system."),
        ],
    },
}
