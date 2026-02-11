#!/usr/bin/env bash
set +e
cd "/home/username/Рабочий стол/my py/ChemistryBots/parent_bot" || exit 1
bash "./run_bot.sh"
ec=$?
echo
echo "Exit code: $ec"
echo
read -r -p "Press Enter to close..."
exit "$ec"
