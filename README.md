# zimpy: self-host wikipedia using zim files

If you get annoyed by banners asking for money or all of the different layouts across different wikipedia pages, **zimpy** might be the thing you are looking for. Simply download a wikipedia dump and host it yourself, with full control over the layout etc. 

<div align="center">
![zimpy](./electrocat.png)
</div>

## Setup

Clone the repository and install the dependencies.

```sh
git clone https://github.com/squarra/zimpy.git
cd zimpy
pip install -r requirements.txt
```

Download a wikipedia zim file. You can get one from [here](https://dumps.wikimedia.org/other/kiwix/zim/wikipedia/). Select the correct language and what topic you want (`wikipedia_en_all_maxi_*` includes all of english wikipedia).

Move the zim file to the repository's directory and either change the name of the file to `wiki.zim` or provide the file name to `Wikiserver` in `main.py`. Then simply run `main.py`.

```sh
python main.py
```

You should see the database getting set up, which might take a few seconds and you can then access the server at `localhost:4321` or provide a custom port.

## Acknowledgments

- [pyzim-tools](https://github.com/kymeria/pyzim-tools): Portions of the codebase are modified from this repository. The original code is licensed under GPLv3.0.
- [ZIMply](https://github.com/kimbauters/ZIMply): If zimpy throws errors for you, you can look at ZIMply which is a more complex self hosted wikipedia server.
