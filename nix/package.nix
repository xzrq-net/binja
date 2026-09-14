{ pkgs, lib, stdenvNoCC, requireFile, unzip, rustPlatform, python3 }:
let
  version = "6.0.10601";
  archive = requireFile {
    name = "binaryninja_linux_${version}_personal.zip";
    hash = "sha256-OOuY5Pw6I5iL3CrDDEPDj2UysjD2ZlADAw7L+SGVRMc=";
    message = ''
      Supply the licensed Binary Ninja ${version} Personal Linux archive:
        nix-store --add-fixed sha256 /path/to/binaryninja_linux_${version}_personal.zip
      The license is supplied at runtime, never to this derivation.
    '';
  };
  vendor = stdenvNoCC.mkDerivation {
    pname = "binaryninja-personal";
    inherit version;
    src = archive;
    nativeBuildInputs = [ unzip ];
    installPhase = ''mkdir -p $out; cp -a . $out/'';
    dontFixup = true;
    preferLocalBuild = true;
    allowSubstitutes = false;
    meta.license = lib.licenses.unfree;
  };
  runtime = pkgs.buildFHSEnv {
    name = "binja-runtime";
    targetPkgs = p: with p; [
      curl dbus fontconfig freetype libGL libxkbcommon libxml2 openssl
      stdenv.cc.cc.lib wayland libx11 libxcb libxcb-image libxcb-keysyms
      libxcb-render-util libxcb-wm zlib
    ];
    runScript = pkgs.writeShellScript "binja-vendor" ''
      unset PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH
      export PYTHONNOUSERSITE=1
      exec ${vendor}/binaryninja "$@"
    '';
  };
in rustPlatform.buildRustPackage {
  pname = "binja";
  version = "0.1.0";
  src = lib.cleanSource ../.;
  cargoLock.lockFile = ../Cargo.lock;
  nativeBuildInputs = [ python3 ];
  postInstall = ''
    mkdir -p $out/lib $out/share/binja
    cp -r binja $out/lib/
    cp -r licenses $out/share/binja/
    cat > $out/lib/binja/build.json <<EOF
    {"version":"${version}","vendor":"${vendor}","runtime":"${runtime}/bin/binja-runtime","labwc":"${pkgs.labwc}/bin/labwc","wayvnc":"${pkgs.wayvnc}/bin/wayvnc","grim":"${pkgs.grim}/bin/grim","wtype":"${pkgs.wtype}/bin/wtype","wlrctl":"${pkgs.wlrctl}/bin/wlrctl","timeout":"${pkgs.coreutils}/bin/timeout"}
    EOF
    PYTHONPATH=$out/lib ${python3}/bin/python3 -P -m binja.api \
      ${vendor}/python/binaryninja $out/lib/binja/api-index.json
  '';
  passthru = { inherit vendor runtime; };
  preferLocalBuild = true;
  allowSubstitutes = false;
  meta = { mainProgram = "binja"; platforms = [ "x86_64-linux" ]; };
}
