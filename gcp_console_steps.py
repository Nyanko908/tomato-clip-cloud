# -*- coding: utf-8 -*-
"""
gcp_console_steps.py
Google Cloud ConsoleでOAuthクライアントID(デスクトップアプリ)を作成する手順を
「コードではなくデータ」として持つ。Google側のUI変更があった場合は、
このファイルの文言/セレクタだけを直せば済むようにする。

各ステップの "name" は Playwright の get_by_role(role, name=...) に渡す
アクセシブルネーム(言語ごと)。Googleの実UIの表示文言と完全一致している保証は
ないため、browser_automation.py 側は各ステップの実行に失敗しても例外を投げて
落ちるのではなく、呼び出し元が手動チュートリアルにフォールバックできるように
設計してある(このファイル自体は純粋なデータであり、フォールバック処理は持たない)。
"""

# Google Cloud Consoleの認証情報ページの直リンク
# project_id が分かっていれば ?project= を付与し、不明ならプロジェクト未指定のままにする
# (Consoleが自動で直近プロジェクトを選ぶか、プロジェクト選択/作成のUIを出す)
CREDENTIALS_URL = "https://console.cloud.google.com/apis/credentials"

# ログイン画面へリダイレクトされた際に表示する案内文
LOGIN_WAIT_LABEL = {
    "ja": "ブラウザでGoogleアカウントにログインしてください（このまま自動で続きます）…",
    "en": "Please sign in to your Google account in the browser (this will continue automatically)…",
    "es": "Inicia sesión en tu cuenta de Google en el navegador (esto continuará automáticamente)…",
    "pt": "Faça login na sua conta do Google no navegador (isso continuará automaticamente)…",
    "de": "Bitte melde dich im Browser mit deinem Google-Konto an (es geht automatisch weiter)…",
    "fr": "Connectez-vous à votre compte Google dans le navigateur (la suite est automatique)…",
    "id": "Silakan masuk ke akun Google Anda di browser (ini akan otomatis dilanjutkan)…",
    "hi": "कृपया ब्राउज़र में अपने Google खाते में लॉगिन करें (यह अपने आप जारी रहेगा)…",
    "ko": "브라우저에서 Google 계정으로 로그인해 주세요(로그인 후 자동으로 계속됩니다)…",
    "it": "Accedi al tuo account Google nel browser (proseguirà automaticamente)…",
    "tr": "Lütfen tarayıcıda Google hesabınızla oturum açın (bu işlem otomatik olarak devam edecek)…",
    "nl": "Log in bij je Google-account in de browser (dit gaat automatisch verder)…",
}

OAUTH_CLIENT_STEPS = [
    {
        "id": "goto_credentials",
        "action": "goto",
        "url": CREDENTIALS_URL,
        "label": {
            "ja": "認証情報ページを開いています…",
            "en": "Opening the credentials page…",
            "es": "Abriendo la página de credenciales…",
            "pt": "Abrindo a página de credenciais…",
            "de": "Anmeldedaten-Seite wird geöffnet…",
            "fr": "Ouverture de la page des identifiants…",
            "id": "Membuka halaman kredensial…",
            "hi": "क्रेडेंशियल पेज खोला जा रहा है…",
            "ko": "사용자 인증 정보 페이지를 여는 중…",
            "it": "Apertura della pagina delle credenziali…",
            "tr": "Kimlik bilgileri sayfası açılıyor…",
            "nl": "Referentiespagina wordt geopend…",
        },
    },
    {
        "id": "click_create_credentials",
        "action": "click",
        "role": "button",
        "name": {
            "ja": "認証情報を作成", "en": "Create Credentials", "es": "Crear credenciales",
            "pt": "Criar credenciais", "de": "Anmeldedaten erstellen", "fr": "Créer des identifiants",
            "id": "Buat kredensial", "hi": "क्रेडेंशियल बनाएं", "ko": "사용자 인증 정보 만들기",
            "it": "Crea credenziali", "tr": "Kimlik bilgileri oluştur", "nl": "Referenties maken",
        },
        "label": {
            "ja": "「認証情報を作成」をクリックしています…",
            "en": "Clicking \"Create Credentials\"…",
            "es": "Haciendo clic en \"Crear credenciales\"…",
            "pt": "Clicando em \"Criar credenciais\"…",
            "de": "Klicke auf \"Anmeldedaten erstellen\"…",
            "fr": "Clic sur « Créer des identifiants »…",
            "id": "Mengklik \"Buat kredensial\"…",
            "hi": "\"क्रेडेंशियल बनाएं\" पर क्लिक कर रहे हैं…",
            "ko": "\"사용자 인증 정보 만들기\"를 클릭하는 중…",
            "it": "Clic su \"Crea credenziali\"…",
            "tr": "\"Kimlik bilgileri oluştur\" tıklanıyor…",
            "nl": "Klikken op \"Referenties maken\"…",
        },
    },
    {
        "id": "click_oauth_client_id",
        "action": "click",
        "role": "menuitem",
        "name": {
            "ja": "OAuth クライアント ID", "en": "OAuth client ID", "es": "ID de cliente de OAuth",
            "pt": "ID do cliente OAuth", "de": "OAuth-Client-ID", "fr": "ID client OAuth",
            "id": "ID klien OAuth", "hi": "OAuth क्लाइंट आईडी", "ko": "OAuth 클라이언트 ID",
            "it": "ID client OAuth", "tr": "OAuth istemci kimliği", "nl": "OAuth-client-ID",
        },
        "label": {
            "ja": "「OAuth クライアント ID」を選択しています…",
            "en": "Selecting \"OAuth client ID\"…",
            "es": "Seleccionando \"ID de cliente de OAuth\"…",
            "pt": "Selecionando \"ID do cliente OAuth\"…",
            "de": "Wähle \"OAuth-Client-ID\"…",
            "fr": "Sélection de « ID client OAuth »…",
            "id": "Memilih \"ID klien OAuth\"…",
            "hi": "\"OAuth क्लाइंट आईडी\" चुन रहे हैं…",
            "ko": "\"OAuth 클라이언트 ID\"를 선택하는 중…",
            "it": "Selezione di \"ID client OAuth\"…",
            "tr": "\"OAuth istemci kimliği\" seçiliyor…",
            "nl": "\"OAuth-client-ID\" selecteren…",
        },
    },
    {
        "id": "select_desktop_app",
        "action": "select_option",
        "role": "combobox",
        "name": {
            "ja": "デスクトップ アプリ", "en": "Desktop app", "es": "Aplicación de escritorio",
            "pt": "Aplicativo para computador", "de": "Desktop-App", "fr": "Application de bureau",
            "id": "Aplikasi desktop", "hi": "डेस्कटॉप ऐप", "ko": "데스크톱 앱",
            "it": "App desktop", "tr": "Masaüstü uygulaması", "nl": "Desktoptoepassing",
        },
        "label": {
            "ja": "「デスクトップ アプリ」を選択しています…",
            "en": "Selecting \"Desktop app\"…",
            "es": "Seleccionando \"Aplicación de escritorio\"…",
            "pt": "Selecionando \"Aplicativo para computador\"…",
            "de": "Wähle \"Desktop-App\"…",
            "fr": "Sélection de « Application de bureau »…",
            "id": "Memilih \"Aplikasi desktop\"…",
            "hi": "\"डेस्कटॉप ऐप\" चुन रहे हैं…",
            "ko": "\"데스크톱 앱\"을 선택하는 중…",
            "it": "Selezione di \"App desktop\"…",
            "tr": "\"Masaüstü uygulaması\" seçiliyor…",
            "nl": "\"Desktoptoepassing\" selecteren…",
        },
    },
    {
        "id": "fill_name",
        "action": "fill",
        "role": "textbox",
        "value": "Tomato Clip",
        "label": {
            "ja": "名前を入力しています…", "en": "Entering a name…", "es": "Introduciendo un nombre…",
            "pt": "Inserindo um nome…", "de": "Name wird eingegeben…", "fr": "Saisie du nom…",
            "id": "Memasukkan nama…", "hi": "नाम दर्ज कर रहे हैं…", "ko": "이름을 입력하는 중…",
            "it": "Inserimento del nome…", "tr": "Ad giriliyor…", "nl": "Naam invoeren…",
        },
    },
    {
        "id": "click_create",
        "action": "click",
        "role": "button",
        "name": {
            "ja": "作成", "en": "Create", "es": "Crear", "pt": "Criar", "de": "Erstellen",
            "fr": "Créer", "id": "Buat", "hi": "बनाएं", "ko": "만들기", "it": "Crea",
            "tr": "Oluştur", "nl": "Maken",
        },
        "label": {
            "ja": "OAuthクライアントIDを作成しています…",
            "en": "Creating the OAuth client ID…",
            "es": "Creando el ID de cliente de OAuth…",
            "pt": "Criando o ID do cliente OAuth…",
            "de": "OAuth-Client-ID wird erstellt…",
            "fr": "Création de l'ID client OAuth…",
            "id": "Membuat ID klien OAuth…",
            "hi": "OAuth क्लाइंट आईडी बनाई जा रही है…",
            "ko": "OAuth 클라이언트 ID를 만드는 중…",
            "it": "Creazione dell'ID client OAuth…",
            "tr": "OAuth istemci kimliği oluşturuluyor…",
            "nl": "OAuth-client-ID wordt gemaakt…",
        },
    },
    {
        "id": "download_json",
        "action": "click_and_download",
        "role": "button",
        "name": {
            "ja": "JSON をダウンロード", "en": "Download JSON", "es": "Descargar JSON",
            "pt": "Baixar JSON", "de": "JSON herunterladen", "fr": "Télécharger le fichier JSON",
            "id": "Download JSON", "hi": "JSON डाउनलोड करें", "ko": "JSON 다운로드",
            "it": "Scarica JSON", "tr": "JSON indir", "nl": "JSON downloaden",
        },
        "label": {
            "ja": "JSONファイルをダウンロードしています…",
            "en": "Downloading the JSON file…",
            "es": "Descargando el archivo JSON…",
            "pt": "Baixando o arquivo JSON…",
            "de": "JSON-Datei wird heruntergeladen…",
            "fr": "Téléchargement du fichier JSON…",
            "id": "Mengunduh file JSON…",
            "hi": "JSON फ़ाइल डाउनलोड की जा रही है…",
            "ko": "JSON 파일을 다운로드하는 중…",
            "it": "Download del file JSON…",
            "tr": "JSON dosyası indiriliyor…",
            "nl": "JSON-bestand wordt gedownload…",
        },
    },
]

# 普段使いのブラウザを一旦終了する際に表示する案内文
CLOSING_BROWSER_LABEL = {
    "ja": "普段お使いのブラウザを一旦終了しています…（開いていたタブは失われます）",
    "en": "Closing your existing browser windows for a moment… (open tabs will be lost)",
    "es": "Cerrando temporalmente tu navegador… (se perderán las pestañas abiertas)",
    "pt": "Fechando seu navegador temporariamente… (as abas abertas serão perdidas)",
    "de": "Dein Browser wird kurz geschlossen… (offene Tabs gehen dabei verloren)",
    "fr": "Fermeture temporaire de votre navigateur… (les onglets ouverts seront perdus)",
    "id": "Menutup browser Anda sebentar… (tab yang terbuka akan hilang)",
    "hi": "आपका ब्राउज़र थोड़ी देर के लिए बंद किया जा रहा है… (खुले टैब खो जाएंगे)",
    "ko": "잠시 브라우저를 종료합니다… (열려 있던 탭은 사라집니다)",
    "it": "Chiusura temporanea del browser… (le schede aperte andranno perse)",
    "tr": "Tarayıcınız kısa süreliğine kapatılıyor… (açık sekmeler kaybolacak)",
    "nl": "Je browser wordt tijdelijk gesloten… (open tabbladen gaan verloren)",
}

# Googleの自動化ブラウザ検知にひっかかった際に表示される文言の一部
# (DOMテキストにこれらが含まれていたら「ブロックされた」と判定してフォールバックする)
BLOCK_SIGNATURES = [
    "This browser or app may not be secure",
    "このブラウザまたはアプリは安全でない可能性があります",
    "couldn't sign you in",
    "ログインできませんでした",
]
