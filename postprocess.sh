#!/bin/bash

sed -Ei 's/\\//g' $1
sed -Ei 's/\./_/g' $1
