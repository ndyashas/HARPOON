#!/bin/bash

yosys ./utils/yosys-synth-script.ys

sed -Ei 's/\\//g' ./generated/yosys-synth.v
sed -Ei 's/([a-zA-Z0-9])\.([a-zA-Z0-9])/\1_\2/g' ./generated/yosys-synth.v

python3 -c "import circuitgraph as cg;\
	    dffsr_bb = cg.BlackBox('DFFSR', ['R', 'S', 'C', 'D'], ['Q']);\
	    ck = cg.from_file('./generated/yosys-synth.v',blackboxes = [dffsr_bb]);\
	    cg.to_file(ck, './generated/final-synth.v')"
