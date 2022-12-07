s27: obfuscate.py ref/s27.v
	python3 obfuscate.py -t s27 -f=ref/s27.v -k 10 -i 5

clean:
	$(RM) *.v *.png key.txt
	$(RM) -r generated

