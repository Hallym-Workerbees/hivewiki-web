{
  description = "Djange devShell environment for Nix users";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
  };

  outputs = inputs @ {flake-parts, ...}:
    flake-parts.lib.mkFlake {inherit inputs;} {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      perSystem = {
        pkgs,
        system,
        ...
      }: let
        isDarwin = pkgs.stdenv.isDarwin;
        isLinux = pkgs.stdenv.isLinux;
      in {
        devShells.default = pkgs.mkShell {
          name = "hivewiki-web";
          packages = with pkgs; [
            python312
            uv
            git
            pre-commit
          ];
          shellHook = ''
            uv venv --allow-existing
            source .venv/bin/activate

            uv sync
            uv run pre-commit install --hook-type pre-commit --hook-type commit-msg

            echo -e "❄️❤️🐍 \e[32mNix Shell Initialized successfully!\e[0m"
          '';
        };
      };
    };
}
