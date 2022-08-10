# Spanner V2

## Downloading
### Simple
1. Run
```sh
$ pip install pipx;pipx install git+https://github.com/EEKIM10/spanner-v2.git
```

### The old way (or development)
1. clone https://github.com/EEKIM10/spanner-v2.git
2. cd into it
3. run `pip install --editable .`
4. run `python -m spanner setup`
5. run `python -m spanner run`

OR without using pip install

3. create your config.json file
4. run `python src run`

## Important change as of 11/06/2022
Configuration is now held in a config.json file, as we outgrew .env files.
While .env files will still work, we recommend you switch to the new config.json system,
as environment variables will stop being able to change new features.

If you don't want to re-write your .env into json, you can use the new CLI tool
to do it for you! run `spanner convert`!
