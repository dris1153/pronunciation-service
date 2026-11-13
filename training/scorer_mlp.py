"""Phone-score MLP for the v2 scorer (trained with torch, served with numpy)."""
from __future__ import annotations

import zlib

import numpy as np
import torch

from app.services.v2.scorer import Z_CLIP, Mlp

HIDDEN, DROPOUT, WEIGHT_DECAY, LR, EPOCHS, BATCH = 128, 0.2, 1e-2, 2e-3, 60, 256


def fit_mlp(x: np.ndarray, y: np.ndarray, groups: np.ndarray, seed: int = 0) -> Mlp:
    """Train on 90% of speakers; keep the epoch with the best PCC on the other 10%."""
    torch.manual_seed(seed)
    mean, std = x.mean(0), np.maximum(x.std(0), 1e-6)
    val = np.array([zlib.crc32(("val" + g).encode()) % 10 == 0 for g in groups])
    z = torch.tensor(np.clip((x - mean) / std, -Z_CLIP, Z_CLIP), dtype=torch.float32)
    yt = torch.tensor(y, dtype=torch.float32)
    net = torch.nn.Sequential(
        torch.nn.Linear(x.shape[1], HIDDEN), torch.nn.ReLU(), torch.nn.Dropout(DROPOUT),
        torch.nn.Linear(HIDDEN, HIDDEN), torch.nn.ReLU(), torch.nn.Dropout(DROPOUT),
        torch.nn.Linear(HIDDEN, 1),
    )
    opt = torch.optim.AdamW(net.parameters(), LR, weight_decay=WEIGHT_DECAY)
    tr_idx = torch.tensor(np.flatnonzero(~val))
    best_r, best_state = -1.0, None
    for _ in range(EPOCHS):
        net.train()
        perm = tr_idx[torch.randperm(len(tr_idx))]
        for i in range(0, len(perm), BATCH):
            b = perm[i:i + BATCH]
            opt.zero_grad()
            torch.nn.functional.mse_loss(net(z[b]).squeeze(1), yt[b]).backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            r = np.corrcoef(net(z[val]).squeeze(1).numpy(), y[val])[0, 1]
        if r > best_r:
            best_r, best_state = r, {k: v.clone() for k, v in net.state_dict().items()}
    net.load_state_dict(best_state)
    lin = [m for m in net if isinstance(m, torch.nn.Linear)]
    layers = [(m.weight.detach().numpy().T.astype(float), m.bias.detach().numpy().astype(float)) for m in lin]
    return Mlp(mean, std, layers)
