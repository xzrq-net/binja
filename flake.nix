{
  description = "Headless Binary Ninja";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = {nixpkgs, ...}: let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
    binja = pkgs.callPackage ./nix/package.nix {};
  in {
    packages.${system} = {
      default = binja;
      inherit binja;
      runtime = binja.runtime;
      vendor = binja.vendor;
    };
    devShells.${system}.default = pkgs.mkShell {
      packages = [ pkgs.python3 pkgs.cargo pkgs.rustc binja ];
    };
  };
}
