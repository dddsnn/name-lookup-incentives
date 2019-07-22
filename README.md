# Incentive System for a Name-Lookup Service
The stuff in /thesis describes what this is all about.

The simulation is in /simulation/src. To run it, you need a `.settings` file.
/simulation/default.settings is the commented default you can start from.

To run the simulation from within /simulation/src, do

    python simulation.py <path/to/some.settings> [duration]

This runs the simulation for the specified duration. The duration is optional,
the simulation will run infinitely if left out. To end the simulation, send the
process a SIGINT.

Once the simulation has ended, it will write its log to a file with the same
base name as the settings file and a `.log` extension.

This log file can be loaded by the Logger class from the analyze module to
examine what happened during the simulation.
