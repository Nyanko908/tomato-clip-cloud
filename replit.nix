# Replit の Nix 環境。ffmpeg をシステムに入れる（moviepy/yt-dlp のマージに必須）。
{ pkgs }: {
  deps = [
    pkgs.python312
    pkgs.ffmpeg
    pkgs.python312Packages.pip
  ];
}
