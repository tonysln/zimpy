# zimpy: Personal Wikipedia Hosting

zimpy enables you to host Wikipedia content locally through a simplified Flask webserver. It is designed to be used with ZIM files, which are offline Wikipedia archives. This project is built for my specific use case and is not designed for broad compatibility. If your ZIM file structure diverges from the one I used, or if you are utilizing a different Python version, the program will most likely break. For a more versatile ZIM file reader, please refer to [ZIMply](https://github.com/kimbauters/ZIMply). Be free to open an issue or pull request if you have any suggestions or improvements.

## Table of Contents
- [Features](#features)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [License](#license)
- [Acknowledgements](#acknowledgements)

## Features
- **ZIM File Reading**: Parses and reads ZIM files, displaying numerous articles and images.
- **Local Hosting**: Provides offline access to Wikipedia content through a Flask webserver.
- **Search Capability**: Implements an SQLite database to facilitate quick searches through Wikipedia articles.

## Getting Started

### Prerequisites
- Python 3.8 or later

### Installation
1. Clone the repo:
```bash
git clone https://github.com/pierresquarra/zimpy
```
2. Navigate to the project directory and install the dependencies:
```bash
cd zimpy
pip install -r requirements.txt
```

## Usage
1. Ensure you have a ZIM file for the Wikipedia content you intend to display.
2. Run the server script:
```bash
python main.py
```
3. The database is then populated with the contents of the ZIM file. This may take a few minutes.
4. Access the hosted content by navigating to `127.0.0.1:5000` in your web browser.

### Custom Templates
You can modify the default template in `templates/base.html` or provide a new template as an argument to `ZIMServer`. Ensure that custom templates are placed in the `templates` directory.

```python
from zimpy import ZIMServer

server = ZIMServer("wiki.zim", "your_custom_template.html")
server.app.run()
```

## License
Distributed under the GNU General Public License v3.0. See `LICENSE` for more information.

## Acknowledgements
- [pyzim-tools](https://github.com/kymeria/pyzim-tools): Portions of the codebase are modified from this repository. The original code is licensed under GPLv3.0.
- [ZIMply](https://github.com/kimbauters/ZIMply): Inspired the creation of this project and serves as a reference for a more broadly compatible ZIM file reader.
