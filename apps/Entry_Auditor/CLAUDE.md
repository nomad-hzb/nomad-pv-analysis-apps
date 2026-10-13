# Entry_Auditor: corrections write to NOMAD

- A correction changes the one value at its flattened path (`modify_file_field`, path-exact) inside the `data` wrapper of the entry's own file, after a preview and a confirm, with a backup in `entry_auditor_backups/`; never a regex over the file text.
- The upload goes back into the entry's own upload folder and is read back to verify. Do not weaken any of these steps (issue #56 was exactly this).
