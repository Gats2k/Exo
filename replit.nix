{pkgs}: {
  deps = [
    pkgs.rustc
    pkgs.pkg-config
    pkgs.libxcrypt
    pkgs.libiconv
    pkgs.cargo
    pkgs.glibcLocales
    pkgs.iana-etc
    pkgs.postgresql
    pkgs.openssl
  ];
}
