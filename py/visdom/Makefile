clean:
	rm -rf ./test_data/*

serve_test:
	python3 -mpdb -cc server.py -env_path test_data -eager_data_loading -logging_level 5

test_simple:
	python3 test_simple.py
