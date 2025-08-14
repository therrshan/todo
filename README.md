# Todo App

Simple Flask todo application.

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Default password: `opensesame`

## Auto-start with systemd

Create service file:
```bash
sudo nano /etc/systemd/system/todo-app.service
```

Service file content:
```ini
[Unit]
Description=Todo App Flask Service
After=network.target

[Service]
Type=simple
User=yourusername
Group=yourusername
WorkingDirectory=/home/yourusername/todo-app
Environment=PATH=/home/yourusername/todo-app/.venv/bin
ExecStart=/home/yourusername/todo-app/.venv/bin/python3 app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable todo-app
sudo systemctl start todo-app
```