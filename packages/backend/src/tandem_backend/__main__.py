from .cli.commands import main

# Guarded: spawned analysis workers import the parent's main module as __mp_main__.
if __name__ == "__main__":
    main()
