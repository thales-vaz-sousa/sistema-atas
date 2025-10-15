CREATE TABLE IF NOT EXISTS atas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT DEFAULT 'pendente'
);

CREATE TABLE IF NOT EXISTS sacramental (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ata_id INTEGER,
    presidido TEXT,
    dirigido TEXT,
    pianista TEXT, -- NOVO CAMPO
    regente_musica TEXT,
    anuncios TEXT, -- NOVO CAMPO (armazenaremos como JSON)
    hinos TEXT,
    oracoes TEXT,
    discursantes TEXT,
    hino_sacramental TEXT,
    hino_intermediario TEXT,
    FOREIGN KEY(ata_id) REFERENCES atas(id)
);

CREATE TABLE IF NOT EXISTS batismo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ata_id INTEGER,
    dedicado TEXT,
    presidido TEXT,
    dirigido TEXT,
    batizados TEXT,
    testemunha1 TEXT,
    testemunha2 TEXT,
    FOREIGN KEY(ata_id) REFERENCES atas(id)
);