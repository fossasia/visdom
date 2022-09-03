clean:
	rm -rf ./test_data/*

serve_test:
	python3 -mpdb -cc server.py -env_path test_data -eager_data_loading -logging_level 5

serve_test_jpwa:
	python3 -mpdb -cc server.py -env_path test_data -eager_data_loading -logging_level 5 -cache_type JPWA

serve_test_jpe:
	python3 -mpdb -cc server.py -env_path test_data -eager_data_loading -logging_level 5 -cache_type JPE

serve_test_jpw:
	python3 -mpdb -cc server.py -env_path test_data -eager_data_loading -logging_level 5 -cache_type JPW


test_save.py:
	python3 test_save.py
test_cache.py:
	python3 test_cache.py
.PHONY: test_cache.py test_save.py
