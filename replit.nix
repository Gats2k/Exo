{pkgs}: {
  deps = [
    pkgs.mailutils
    pkgs.docker_26
    pkgs.glibcLocales
    pkgs.iana-etc
    pkgs.postgresql
    pkgs.openssl
    pkgs.pandoc
    pkgs.texlive.combined.scheme-full
    pkgs.zip
  ];
}
