# -*- coding: utf-8 -*-
"""
api_tutorials.py - APIキー取得方法のチュートリアル本文（12言語対応）

i18n.py と同じ方針: 静的に事前翻訳した文言を持つ（リアルタイム翻訳はしない）。
理由: Gemini APIキー取得チュートリアル自体をGemini APIで翻訳すると、
まだキーを持たないユーザーにとって鶏と卵の関係になるため。
"""

TUTORIALS = {

"gemini_key": {
    "ja": {
        "title": "Gemini APIキーの取得方法",
        "steps": [
            "aistudio.google.com を開き、Googleアカウントでログインする",
            "左メニューの「Get API key」→「Create API key」をクリック",
            "プロジェクトを選択する（なければ自動で作成されます）",
            "生成されたキーをコピーして、このウィザードの入力欄に貼り付ける",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "en": {
        "title": "How to get a Gemini API key",
        "steps": [
            "Open aistudio.google.com and sign in with your Google account",
            'In the left menu, click "Get API key" → "Create API key"',
            "Select a project (one will be created automatically if you don't have one)",
            "Copy the generated key and paste it into this wizard's input field",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "es": {
        "title": "Cómo obtener una clave de API de Gemini",
        "steps": [
            "Abre aistudio.google.com e inicia sesión con tu cuenta de Google",
            'En el menú izquierdo, haz clic en "Get API key" → "Create API key"',
            "Selecciona un proyecto (se creará uno automáticamente si no tienes ninguno)",
            "Copia la clave generada y pégala en el campo de este asistente",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "pt": {
        "title": "Como obter uma chave de API do Gemini",
        "steps": [
            "Abra aistudio.google.com e faça login com sua conta do Google",
            'No menu esquerdo, clique em "Get API key" → "Create API key"',
            "Selecione um projeto (um será criado automaticamente se você não tiver nenhum)",
            "Copie a chave gerada e cole no campo deste assistente",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "de": {
        "title": "So erhältst du einen Gemini-API-Schlüssel",
        "steps": [
            "Öffne aistudio.google.com und melde dich mit deinem Google-Konto an",
            'Klicke im linken Menü auf "Get API key" → "Create API key"',
            "Wähle ein Projekt aus (falls du keins hast, wird automatisch eines erstellt)",
            "Kopiere den generierten Schlüssel und füge ihn in das Eingabefeld dieses Assistenten ein",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "fr": {
        "title": "Comment obtenir une clé API Gemini",
        "steps": [
            "Ouvrez aistudio.google.com et connectez-vous avec votre compte Google",
            "Dans le menu de gauche, cliquez sur « Get API key » → « Create API key »",
            "Sélectionnez un projet (un sera créé automatiquement si vous n'en avez pas)",
            "Copiez la clé générée et collez-la dans le champ de cet assistant",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "id": {
        "title": "Cara mendapatkan kunci API Gemini",
        "steps": [
            "Buka aistudio.google.com dan masuk dengan akun Google Anda",
            'Di menu kiri, klik "Get API key" → "Create API key"',
            "Pilih proyek (akan dibuat otomatis jika Anda belum punya)",
            "Salin kunci yang dihasilkan dan tempel di kolom input wizard ini",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "hi": {
        "title": "Gemini API कुंजी कैसे प्राप्त करें",
        "steps": [
            "aistudio.google.com खोलें और अपने Google खाते से लॉगिन करें",
            'बाईं मेनू में "Get API key" → "Create API key" पर क्लिक करें',
            "एक प्रोजेक्ट चुनें (अगर आपके पास नहीं है तो अपने आप बन जाएगा)",
            "जनरेट की गई कुंजी कॉपी करें और इस विज़ार्ड के इनपुट फ़ील्ड में पेस्ट करें",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "ko": {
        "title": "Gemini API 키를 받는 방법",
        "steps": [
            "aistudio.google.com을 열고 Google 계정으로 로그인하세요",
            '왼쪽 메뉴에서 "Get API key" → "Create API key"를 클릭하세요',
            "프로젝트를 선택하세요(없으면 자동으로 생성됩니다)",
            "생성된 키를 복사하여 이 마법사의 입력란에 붙여넣으세요",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "it": {
        "title": "Come ottenere una chiave API Gemini",
        "steps": [
            "Apri aistudio.google.com e accedi con il tuo account Google",
            'Nel menu a sinistra, fai clic su "Get API key" → "Create API key"',
            "Seleziona un progetto (ne verrà creato uno automaticamente se non ne hai)",
            "Copia la chiave generata e incollala nel campo di questa procedura guidata",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "tr": {
        "title": "Gemini API anahtarı nasıl alınır",
        "steps": [
            "aistudio.google.com'u açın ve Google hesabınızla oturum açın",
            '"Get API key" → "Create API key" seçeneğine sol menüden tıklayın',
            "Bir proje seçin (hiç yoksa otomatik olarak oluşturulur)",
            "Oluşturulan anahtarı kopyalayıp bu sihirbazın giriş alanına yapıştırın",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
    "nl": {
        "title": "Zo krijg je een Gemini API-sleutel",
        "steps": [
            "Open aistudio.google.com en log in met je Google-account",
            'Klik in het linkermenu op "Get API key" → "Create API key"',
            "Selecteer een project (er wordt automatisch een aangemaakt als je er geen hebt)",
            "Kopieer de gegenereerde sleutel en plak deze in het invoerveld van deze wizard",
        ],
        "doc_url": "https://ai.google.dev/gemini-api/docs/api-key",
    },
},

"youtube_key": {
    "ja": {
        "title": "YouTube Data APIキーの取得方法",
        "steps": [
            "console.cloud.google.com を開き、プロジェクトを作成する（または既存のものを選択）",
            "「APIとサービス」→「ライブラリ」で「YouTube Data API v3」を検索して有効化する",
            "「APIとサービス」→「認証情報」→「認証情報を作成」→「APIキー」を選択",
            "生成されたキーをコピーして貼り付ける（無料・1日10,000クォータ）",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "en": {
        "title": "How to get a YouTube Data API key",
        "steps": [
            "Open console.cloud.google.com and create a project (or select an existing one)",
            'Go to "APIs & Services" → "Library", search for "YouTube Data API v3" and enable it',
            'Go to "APIs & Services" → "Credentials" → "Create Credentials" → "API Key"',
            "Copy the generated key and paste it in (free, 10,000 quota units/day)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "es": {
        "title": "Cómo obtener una clave de YouTube Data API",
        "steps": [
            "Abre console.cloud.google.com y crea un proyecto (o selecciona uno existente)",
            'Ve a "APIs y servicios" → "Biblioteca", busca "YouTube Data API v3" y actívala',
            'Ve a "APIs y servicios" → "Credenciales" → "Crear credenciales" → "Clave de API"',
            "Copia la clave generada y pégala (gratis, 10,000 unidades de cuota/día)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "pt": {
        "title": "Como obter uma chave da YouTube Data API",
        "steps": [
            "Abra console.cloud.google.com e crie um projeto (ou selecione um existente)",
            'Vá em "APIs e Serviços" → "Biblioteca", procure por "YouTube Data API v3" e ative',
            'Vá em "APIs e Serviços" → "Credenciais" → "Criar Credenciais" → "Chave de API"',
            "Copie a chave gerada e cole (gratuito, 10.000 unidades de cota/dia)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "de": {
        "title": "So erhältst du einen YouTube-Data-API-Schlüssel",
        "steps": [
            "Öffne console.cloud.google.com und erstelle ein Projekt (oder wähle ein vorhandenes aus)",
            'Gehe zu "APIs & Dienste" → "Bibliothek", suche nach "YouTube Data API v3" und aktiviere sie',
            'Gehe zu "APIs & Dienste" → "Anmeldedaten" → "Anmeldedaten erstellen" → "API-Schlüssel"',
            "Kopiere den generierten Schlüssel und füge ihn ein (kostenlos, 10.000 Kontingenteinheiten/Tag)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "fr": {
        "title": "Comment obtenir une clé YouTube Data API",
        "steps": [
            "Ouvrez console.cloud.google.com et créez un projet (ou sélectionnez-en un existant)",
            "Allez dans « APIs et services » → « Bibliothèque », recherchez « YouTube Data API v3 » et activez-la",
            "Allez dans « APIs et services » → « Identifiants » → « Créer des identifiants » → « Clé API »",
            "Copiez la clé générée et collez-la (gratuit, 10 000 unités de quota/jour)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "id": {
        "title": "Cara mendapatkan kunci YouTube Data API",
        "steps": [
            "Buka console.cloud.google.com dan buat proyek (atau pilih yang sudah ada)",
            'Buka "API & Layanan" → "Library", cari "YouTube Data API v3" dan aktifkan',
            'Buka "API & Layanan" → "Kredensial" → "Buat Kredensial" → "Kunci API"',
            "Salin kunci yang dihasilkan dan tempel (gratis, 10.000 unit kuota/hari)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "hi": {
        "title": "YouTube Data API कुंजी कैसे प्राप्त करें",
        "steps": [
            "console.cloud.google.com खोलें और एक प्रोजेक्ट बनाएं (या मौजूदा प्रोजेक्ट चुनें)",
            '"APIs और सेवाएं" → "लाइब्रेरी" में जाएं, "YouTube Data API v3" खोजें और सक्षम करें',
            '"APIs और सेवाएं" → "क्रेडेंशियल" → "क्रेडेंशियल बनाएं" → "API कुंजी" पर जाएं',
            "जनरेट की गई कुंजी कॉपी करके पेस्ट करें (मुफ़्त, 10,000 कोटा यूनिट/दिन)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "ko": {
        "title": "YouTube Data API 키를 받는 방법",
        "steps": [
            "console.cloud.google.com을 열고 프로젝트를 만드세요(또는 기존 프로젝트 선택)",
            '"API 및 서비스" → "라이브러리"에서 "YouTube Data API v3"를 검색하여 사용 설정하세요',
            '"API 및 서비스" → "사용자 인증 정보" → "사용자 인증 정보 만들기" → "API 키"로 이동하세요',
            "생성된 키를 복사하여 붙여넣으세요(무료, 하루 10,000 할당량 단위)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "it": {
        "title": "Come ottenere una chiave YouTube Data API",
        "steps": [
            "Apri console.cloud.google.com e crea un progetto (o selezionane uno esistente)",
            'Vai su "API e servizi" → "Raccolta", cerca "YouTube Data API v3" e attivala',
            'Vai su "API e servizi" → "Credenziali" → "Crea credenziali" → "Chiave API"',
            "Copia la chiave generata e incollala (gratis, 10.000 unità di quota/giorno)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "tr": {
        "title": "YouTube Data API anahtarı nasıl alınır",
        "steps": [
            "console.cloud.google.com'u açın ve bir proje oluşturun (veya mevcut birini seçin)",
            '"API\'ler ve Hizmetler" → "Kitaplık"a gidin, "YouTube Data API v3"ü arayın ve etkinleştirin',
            '"API\'ler ve Hizmetler" → "Kimlik Bilgileri" → "Kimlik Bilgileri Oluştur" → "API Anahtarı"na gidin',
            "Oluşturulan anahtarı kopyalayıp yapıştırın (ücretsiz, günde 10.000 kota birimi)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
    "nl": {
        "title": "Zo krijg je een YouTube Data API-sleutel",
        "steps": [
            "Open console.cloud.google.com en maak een project aan (of selecteer een bestaand project)",
            'Ga naar "API\'s en services" → "Bibliotheek", zoek naar "YouTube Data API v3" en schakel deze in',
            'Ga naar "API\'s en services" → "Referenties" → "Referenties maken" → "API-sleutel"',
            "Kopieer de gegenereerde sleutel en plak deze (gratis, 10.000 quota-eenheden/dag)",
        ],
        "doc_url": "https://developers.google.com/youtube/v3/getting-started",
    },
},

"credentials_path": {
    "ja": {
        "title": "YouTube OAuth2認証ファイルの取得方法",
        "steps": [
            "Google Cloud Console の「APIとサービス」→「認証情報」を開く",
            "「認証情報を作成」→「OAuth クライアント ID」を選択",
            "アプリケーションの種類で「デスクトップアプリ」を選ぶ",
            "作成後、JSONファイルをダウンロードする（この時にしかダウンロードできないので注意）",
            "ダウンロードしたファイルを「参照」ボタンで選択する",
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "en": {
        "title": "How to get the YouTube OAuth2 credentials file",
        "steps": [
            'Open "APIs & Services" → "Credentials" in Google Cloud Console',
            'Click "Create Credentials" → "OAuth client ID"',
            'Choose "Desktop app" as the application type',
            "After creation, download the JSON file (this is the only time you can download it)",
            'Select the downloaded file using the "Browse" button',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "es": {
        "title": "Cómo obtener el archivo de credenciales OAuth2 de YouTube",
        "steps": [
            'Abre "APIs y servicios" → "Credenciales" en Google Cloud Console',
            'Haz clic en "Crear credenciales" → "ID de cliente de OAuth"',
            'Elige "Aplicación de escritorio" como tipo de aplicación',
            "Después de crearla, descarga el archivo JSON (solo se puede descargar en este momento)",
            'Selecciona el archivo descargado con el botón "Examinar"',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "pt": {
        "title": "Como obter o arquivo de credenciais OAuth2 do YouTube",
        "steps": [
            'Abra "APIs e Serviços" → "Credenciais" no Google Cloud Console',
            'Clique em "Criar Credenciais" → "ID do cliente OAuth"',
            'Escolha "Aplicativo para computador" como tipo de aplicativo',
            "Após criar, baixe o arquivo JSON (só é possível baixar neste momento)",
            'Selecione o arquivo baixado usando o botão "Procurar"',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "de": {
        "title": "So erhältst du die YouTube-OAuth2-Anmeldedatendatei",
        "steps": [
            'Öffne "APIs & Dienste" → "Anmeldedaten" in der Google Cloud Console',
            'Klicke auf "Anmeldedaten erstellen" → "OAuth-Client-ID"',
            'Wähle "Desktop-App" als Anwendungstyp',
            "Lade nach der Erstellung die JSON-Datei herunter (nur zu diesem Zeitpunkt möglich)",
            'Wähle die heruntergeladene Datei über die Schaltfläche "Durchsuchen" aus',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "fr": {
        "title": "Comment obtenir le fichier d'identifiants OAuth2 YouTube",
        "steps": [
            "Ouvrez « APIs et services » → « Identifiants » dans Google Cloud Console",
            "Cliquez sur « Créer des identifiants » → « ID client OAuth »",
            "Choisissez « Application de bureau » comme type d'application",
            "Après la création, téléchargez le fichier JSON (téléchargeable uniquement à ce moment-là)",
            "Sélectionnez le fichier téléchargé avec le bouton « Parcourir »",
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "id": {
        "title": "Cara mendapatkan file kredensial OAuth2 YouTube",
        "steps": [
            'Buka "API & Layanan" → "Kredensial" di Google Cloud Console',
            'Klik "Buat Kredensial" → "ID klien OAuth"',
            'Pilih "Aplikasi desktop" sebagai jenis aplikasi',
            "Setelah dibuat, unduh file JSON (hanya bisa diunduh saat itu juga)",
            'Pilih file yang diunduh menggunakan tombol "Jelajahi"',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "hi": {
        "title": "YouTube OAuth2 क्रेडेंशियल फ़ाइल कैसे प्राप्त करें",
        "steps": [
            'Google Cloud Console में "APIs और सेवाएं" → "क्रेडेंशियल" खोलें',
            '"क्रेडेंशियल बनाएं" → "OAuth क्लाइंट ID" पर क्लिक करें',
            'एप्लिकेशन प्रकार के रूप में "डेस्कटॉप ऐप" चुनें',
            "बनाने के बाद, JSON फ़ाइल डाउनलोड करें (यह केवल इसी समय डाउनलोड की जा सकती है)",
            '"ब्राउज़ करें" बटन का उपयोग करके डाउनलोड की गई फ़ाइल चुनें',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "ko": {
        "title": "YouTube OAuth2 인증 파일을 받는 방법",
        "steps": [
            '"API 및 서비스" → "사용자 인증 정보"를 Google Cloud Console에서 여세요',
            '"사용자 인증 정보 만들기" → "OAuth 클라이언트 ID"를 클릭하세요',
            '애플리케이션 유형으로 "데스크톱 앱"을 선택하세요',
            "생성 후 JSON 파일을 다운로드하세요(이때만 다운로드할 수 있습니다)",
            '"찾아보기" 버튼으로 다운로드한 파일을 선택하세요',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "it": {
        "title": "Come ottenere il file delle credenziali OAuth2 di YouTube",
        "steps": [
            'Apri "API e servizi" → "Credenziali" in Google Cloud Console',
            'Fai clic su "Crea credenziali" → "ID client OAuth"',
            'Scegli "App desktop" come tipo di applicazione',
            "Dopo la creazione, scarica il file JSON (scaricabile solo in questo momento)",
            'Seleziona il file scaricato con il pulsante "Sfoglia"',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "tr": {
        "title": "YouTube OAuth2 kimlik bilgileri dosyası nasıl alınır",
        "steps": [
            '"API\'ler ve Hizmetler" → "Kimlik Bilgileri"ni Google Cloud Console\'da açın',
            '"Kimlik Bilgileri Oluştur" → "OAuth istemci kimliği"ne tıklayın',
            'Uygulama türü olarak "Masaüstü uygulaması"nı seçin',
            "Oluşturduktan sonra JSON dosyasını indirin (yalnızca bu sırada indirilebilir)",
            '"Gözat" düğmesini kullanarak indirilen dosyayı seçin',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
    "nl": {
        "title": "Zo krijg je het YouTube OAuth2-referentiebestand",
        "steps": [
            'Open "API\'s en services" → "Referenties" in Google Cloud Console',
            'Klik op "Referenties maken" → "OAuth-client-ID"',
            'Kies "Bureaubladtoepassing" als toepassingstype',
            "Download na het aanmaken het JSON-bestand (dit kan alleen op dit moment)",
            'Selecteer het gedownloade bestand met de knop "Bladeren"',
        ],
        "doc_url": "https://support.google.com/googleapi/answer/6158849",
    },
},

}
