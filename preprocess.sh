#!/bin/bash

sed -E 's/GND,//' $1 | sed -E 's/VDD,//' | sed -E 's/^( )* dff (.*)\((.*),(.*),(.*)\);/\1dff \2\(.reset\(DFF_RESET\), .CK\(\3\),.Q\(\4\),.D\(\5\)\);/' | sed -E 's/\/\/(.*)//'
