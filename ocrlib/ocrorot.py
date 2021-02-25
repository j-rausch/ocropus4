import sys
import random as pyrand
from functools import partial
from math import cos, exp, log, sin
from typing import List
from itertools import islice

import matplotlib.pyplot as plt
import numpy as np
import ocrodeg
import scipy.ndimage as ndi
import torch
import typer
from torch import nn
from torch import optim
from torch.utils.data import DataLoader
import webdataset as wds
import torch.fft

from . import slog
from . import utils
from . import loading

logger = slog.NoLogger()

plt.rc("image", cmap="gray")
plt.rc("image", interpolation="nearest")


app = typer.Typer()


def binned(x, bins):
    return np.argmin(np.abs(np.array(bins) - x))


def unbinned(b, bins):
    return bins[b]


def get_patch(image, shape, center, m=np.eye(2), order=1):
    yx = np.array(center, "f")
    hw = np.array(shape, "f")
    offset = yx - np.dot(m, hw / 2.0)
    return ndi.affine_transform(
        image, m, offset=offset, output_shape=shape, order=order
    )


def degrade_patch(patch):
    p = pyrand.uniform(0.0, 1.0)
    if p < 0.3:
        return patch
    if p < 0.7:
        sigma = pyrand.uniform(0.2, 5.0)
        maxdelta = pyrand.uniform(0.5, 3.0)
        noise = ocrodeg.bounded_gaussian_noise(patch.shape, sigma, maxdelta)
        patch = ocrodeg.distort_with_noise(patch, noise)
        gsigma = pyrand.uniform(0.0, 2.5)
        if gsigma > 0.5:
            patch = ndi.gaussian_filter(patch, gsigma)
        return patch
    else:
        return 1.0 - ocrodeg.printlike_multiscale(1.0 - patch)


def get_patches(
    page,
    shape=(256, 256),
    flip=False,
    invert=False,
    alpha=(0.0, 0.0),
    scale=(1.0, 1.0),
    order=1,
    degrade=False,
    npatches=100,
    ntrials=10000,
):
    h, w = page.shape[:2]
    smooth = ndi.uniform_filter(page, 100)
    mask = smooth > np.percentile(smooth, 70)
    samples = []
    for _ in range(ntrials):
        if len(samples) >= npatches:
            break
        y, x = pyrand.randrange(0, h), pyrand.randrange(0, w)
        if mask[y, x]:
            samples.append((x, y))
    pyrand.shuffle(samples)
    for x, y in samples:
        a = pyrand.uniform(*alpha)
        s = exp(pyrand.uniform(log(scale[0]), log(scale[1])))
        m = np.array([[cos(a), -sin(a)], [sin(a), cos(a)]], "f") / s
        result = get_patch(page, shape, (y, x), m=m, order=order)
        rangle = 0
        if flip:
            rangle = pyrand.choice([0, 1, 2, 3]) * 90
            result = ndi.rotate(result, rangle, order=1)
        inv = 0
        if invert:
            if pyrand.uniform(0.0, 1.0) > 0.5:
                inv = 1
                result = 1.0 - result
        if degrade:
            result = degrade_patch(result)
        yield result, (rangle // 90, a, s, inv)


def rot_pipe(source, shape=(256, 256), alpha=0.1, scale=3.0):
    for (page,) in source:
        if np.mean(page) > 0.5:
            page = 1.0 - page
        for patch, params in get_patches(
            page,
            shape=shape,
            flip=True,
            degrade=True,
            alpha=(-alpha, alpha),
            scale=(1.0 / scale, scale),
        ):
            r, _, _, _ = params
            yield torch.tensor(patch), r


def skew_pipe(source, shape=(256, 256), alpha=(-0.1, 0.1), scale=(0.5, 2.0)):
    for (page,) in source:
        if np.mean(page) > 0.5:
            page = 1.0 - page
        for patch, params in get_patches(
            page, shape=shape, alpha=alpha, scale=scale, degrade=True
        ):
            _, a, s, _ = params
            yield torch.tensor(patch), a, s


def make_loader(
    urls,
    batch_size=16,
    extensions="nrm.jpg;image.png;framed.png;page.png;png;page.jpg;jpg;jpeg",
    shuffle=0,
    num_workers=4,
    pipe=rot_pipe,
    limit=-1,
):
    training = wds.Dataset(urls).shuffle(shuffle).decode("l").to_tuple(extensions)
    training.pipe(pipe)
    if limit > 0:
        training = wds.ResizedDataset(training, limit, limit)
    return DataLoader(training, batch_size=batch_size, num_workers=num_workers)


# class GlobalAvgPool2d(nn.Module):
#     def __init__(self):
#         super().__init__()

#     def forward(self, x):
#         return F.adaptive_avg_pool2d(x, (1, 1))[:, :, 0, 0]


# def block(s, r, repeat=2):
#     result = []
#     for i in range(repeat):
#         result += [flex.Conv2d(8, r, padding=r // 2), flex.BatchNorm2d(), nn.ReLU()]
#     result += [nn.MaxPool2d(2)]
#     return result


# class Spectrum(nn.Module):
#     def __init__(self, nonlin="logplus1"):
#         nn.Module.__init__(self)
#         self.nonlin = nonlin

#     def forward(self, x):
#         inputs = torch.stack([x, torch.zeros_like(x)], dim=-1)
#         mag = torch.fft.fftn(torch.view_as_complex(inputs), dim=(2, 3)).abs()
#         if self.nonlin is None:
#             return mag
#         elif self.nonlin == "logplus1":
#             return (1.0 + mag).log()
#         elif self.nonlin == "sqrt":
#             return mag ** 0.5
#         else:
#             raise ValueError(f"{self.nonlin}: unknown nonlinearity")

#     def __repr__(self):
#         return f"Spectrum-{self.nonlin}"


# def make_model_rot(size=256):
#     r = 3
#     B, D, H, W = (2, 128), (1, 512), size, size
#     model = nn.Sequential(
#         layers.CheckSizes(B, D, H, W),
#         *block(32, r),
#         *block(64, r),
#         *block(96, r),
#         *block(128, r),
#         GlobalAvgPool2d(),
#         flex.Linear(64),
#         nn.BatchNorm1d(64),
#         nn.ReLU(),
#         flex.Linear(4),
#         layers.CheckSizes(B, 4),
#     )
#     flex.shape_inference(model, (2, 1, size, size))
#     return model


# def make_model_skew(noutput, size=256, r=5, nf=8, r2=5, nf2=4):
#     B, D, H, W = (2, 128), (1, 512), size, size
#     model = nn.Sequential(
#         layers.CheckSizes(B, D, H, W),
#         nn.Conv2d(1, nf, r, padding=r // 2),
#         nn.BatchNorm2d(nf),
#         nn.ReLU(),
#         Spectrum(),
#         nn.Conv2d(nf, nf2, r2, padding=r2 // 2),
#         nn.BatchNorm2d(nf2),
#         nn.ReLU(),
#         layers.Reshape(0, [1, 2, 3]),
#         nn.Linear(nf2 * W * H, 128),
#         nn.BatchNorm1d(128),
#         nn.ReLU(),
#         nn.Linear(128, noutput),
#         layers.CheckSizes(B, noutput),
#     )
#     return model


@public
class PageOrientation:
    def __init__(self, fname, check=True):
        self.model = loading.load_only_model(fname)()
        self.check = check

    def orientation(self, page, npatches=200, bs=50):
        if self.check:
            assert np.mean(page) < 0.5
        try:
            self.model.cuda()
            patches = get_patches(page, npatches=npatches)
            result = []
            while True:
                batch = [x[0] for x in islice(patches, bs)]
                if len(batch) == 0:
                    break
                inputs = torch.tensor(batch).unsqueeze(1).cuda()
                outputs = self.model(inputs).softmax(1).cpu().detach()
                result.append(outputs)
            self.last = torch.cat(result)
            self.hist = self.last.mean(0)
            return int(self.hist.argmax()) * 90
        finally:
            self.model.cpu()

    def make_upright(self, page):
        angle = self.orientation(page)
        return ndi.rotate(page, -angle)


@public
class PageSkew:
    def __init__(self, fname, check=True):
        self.model = loading.load_only_model(fname)()
        self.check = check

    def skew(self, page, npatches=200, bs=50):
        if self.check:
            assert np.mean(page) < 0.5
        try:
            self.model.cuda()
            patches = get_patches(page, npatches=npatches)
            result = []
            while True:
                batch = [x[0] for x in islice(patches, bs)]
                if len(batch) == 0:
                    break
                inputs = torch.tensor(batch).unsqueeze(1).cuda()
                outputs = self.model(inputs).softmax(1).cpu().detach()
                result.append(outputs)
            self.last = torch.cat(result)
            self.hist = self.last.mean(0)
            bucket = int(self.last.mean(0).argmax())
            return unbinned(bucket, self.bins)
        finally:
            self.model.cpu()

    def deskew(self, page):
        self.angle = self.skew(page) * 180.0 / np.pi
        return ndi.rotate(page, self.angle, order=1)

@public
class PageScale:
    def __init__(self, fname=None, check=True):
        self.model = loading.load_only_model(fname)()
        self.check = check

    def skew(self, page, npatches=200, bs=50):
        if self.check:
            assert np.mean(page) < 0.5
        try:
            self.model.cuda()
            patches = get_patches(page, npatches=npatches)
            result = []
            while True:
                batch = [x[0] for x in islice(patches, bs)]
                if len(batch) == 0:
                    break
                inputs = torch.tensor(batch).unsqueeze(1).cuda()
                outputs = self.model(inputs).softmax(1).cpu().detach()
                result.append(outputs)
            self.last = torch.cat(result)
            self.hist = self.last.mean(0)
            bucket = int(self.last.mean(0).argmax())
            return unbinned(bucket, self.bins)
        finally:
            self.model.cpu()

    def deskew(self, page):
        self.angle = self.skew(page) * 180.0 / np.pi
        return ndi.rotate(page, self.angle, order=1)


default_extensions = (
    "bin.png;nrm.jpg;nrm.png;image.png;framed.png;page.png;png;page.jpg;jpg;jpeg"
)


@app.command()
def train_rot(
    urls: List[str],
    nsamples: int = 1000000,
    num_workers: int = 8,
    replicate: int = 1,
    bs: int = 64,
    prefix: str = "rot",
    lrfun="0.3**(3+n//5000000)",
    output: str = "",
    model: str = "page_orientation_210113",
    extensions: str = default_extensions,
):
    logger = slog.Logger(fname=output, prefix=prefix)
    logger.sysinfo()
    logger.json("args", sys.argv)
    model = loading.load_or_construct_model(model)
    model.cuda()
    print(model)
    urls = urls * replicate
    training = make_loader(
        urls,
        shuffle=10000,
        num_workers=num_workers,
        batch_size=bs,
        extensions=extensions,
    )
    criterion = nn.CrossEntropyLoss().cuda()
    lrfun = eval(f"lambda n: {lrfun}")
    lr = lrfun(0)
    optimizer = optim.SGD(model.parameters(), lr=lr)
    count = 0
    losses = []

    def save():
        state = dict(
            mdef="",
            msrc="",
            mstate=model.state_dict(),
            ostate=optimizer.state_dict(),
        )
        avgloss = np.mean(losses[-100:])
        logger.save("model", state, scalar=avgloss, step=count)
        logger.flush()
        print("\nsaved at", count)

    schedule = utils.Schedule()

    for patches, targets in utils.repeatedly(training):
        if count > nsamples:
            break
        patches = patches.type(torch.float).unsqueeze(1).cuda()
        optimizer.zero_grad()
        outputs = model(patches)
        loss = criterion(outputs, targets.cuda())
        loss.backward()
        optimizer.step()
        count += len(patches)
        losses.append(float(loss))
        if schedule("info", 60, initial=True):
            print(count, np.mean(losses[-50:]), lr, flush=True)
        if schedule("log", 15 * 60):
            avgloss = np.mean(losses[-100:])
            logger.scalar(
                "train/loss",
                avgloss,
                step=count,
                json=dict(lr=lr),
            )
            logger.flush()
        if schedule("save", 15 * 60):
            save()
        if lrfun(count) != lr:
            lr = lrfun(count)
            optimizer = optim.SGD(model.parameters(), lr=lr)

    save()


@app.command()
def train_skew(
    urls: List[str],
    nsamples: int = 1000000,
    num_workers: int = 8,
    bins: str = "np.linspace(-0.1, 0.1, 21)",
    alpha: str = "-0.1, 0.1",
    scale: str = "0.5, 2.0",
    replicate: int = 1,
    bs: int = 64,
    prefix: str = "skew",
    lrfun: str = "0.3**(3+n//5000000)",
    do_scale: bool = False,
    output: str = "",
    limit: int = -1,
    model: str = "page_skew_210113",
    extensions: str = default_extensions,
):
    """Trains either skew (=small rotation) or scale models."""

    scale = eval(f"[{scale}]")
    alpha = eval(f"[{alpha}]")
    bins = eval(bins)
    logger = slog.Logger(fname=output, prefix=prefix)
    logger.sysinfo()
    logger.json("args", sys.argv)
    model = loading.load_or_construct_model(model, len(bins))
    model.cuda()
    print(model)
    urls = urls * replicate

    pipe = partial(skew_pipe, scale=scale, alpha=alpha)

    training = make_loader(
        urls,
        shuffle=10000,
        num_workers=num_workers,
        batch_size=bs,
        pipe=pipe,
        limit=limit,
        extensions=extensions,
    )
    criterion = nn.CrossEntropyLoss().cuda()
    lrfun = eval(f"lambda n: {lrfun}")
    lr = lrfun(0)
    optimizer = optim.SGD(model.parameters(), lr=lr)
    count = 0
    losses = []
    schedule = utils.Schedule()

    def save():
        state = dict(
            mdef="",
            msrc="",
            mstate=model.state_dict(),
            ostate=optimizer.state_dict(),
        )
        state["bins"] = bins
        avgloss = np.mean(losses[-100:])
        logger.save("model", state, scalar=avgloss, step=count)
        logger.flush()
        print("# saved", count, file=sys.stderr)

    for patches, angles, scales in utils.repeatedly(training, verbose=True):
        if count >= nsamples:
            print("# finished at", count)
            break
        targets = angles if not do_scale else scales
        targets = torch.tensor([binned(float(t), bins) for t in targets])
        patches = patches.type(torch.float).unsqueeze(1).cuda()
        optimizer.zero_grad()
        outputs = model(patches)
        loss = criterion(outputs, targets.cuda())
        loss.backward()
        optimizer.step()
        count += len(patches)
        losses.append(float(loss))
        if schedule("info", 60, initial=True):
            print(count, np.mean(losses[-50:]), lr, flush=True)
        if schedule("log", 10 * 60):
            avgloss = np.mean(losses[-100:])
            logger.scalar(
                "train/loss",
                avgloss,
                step=count,
                json=dict(lr=lr),
            )
            logger.flush()
        if schedule("save", 15 * 60):
            save()
        if lrfun(count) != lr:
            lr = lrfun(count)
            optimizer = optim.SGD(model.parameters(), lr=lr)
    save()


@app.command()
def train_scale(
    urls: List[str],
    nsamples: int = 1000000,
    num_workers: int = 8,
    alpha: str = "-0.1, 0.1",
    scale: str = "0.5, 2.0",
    bins: str = "np.linspace(0.5, 2.0, 21)",
    replicate: int = 1,
    bs: int = 64,
    prefix: str = "scale",
    lrfun: str = "0.3**(3+n//5000000)",
    output: str = "",
    limit: int = -1,
    extensions: str = default_extensions,
):
    return train_skew(
        urls,
        nsamples=nsamples,
        num_workers=num_workers,
        bins=bins,
        alpha=alpha,
        scale=scale,
        replicate=replicate,
        bs=bs,
        prefix=prefix,
        lrfun=lrfun,
        output=output,
        do_scale=True,
        limit=limit,
        extensions=extensions,
    )


@app.command()
def predict(
    urls: List[str],
    rotmodel: str = "",
    skewmodel: str = "",
    extensions: str = default_extensions,
    limit: int = 999999999,
    invert: str = "Auto",
):
    rotest = PageOrientation(rotmodel) if rotmodel != "" else None
    skewest = PageSkew(skewmodel) if skewmodel != "" else None
    dataset = wds.Dataset(urls).decode("l").to_tuple("__key__ " + extensions)
    for key, image in islice(dataset, limit):
        image = utils.autoinvert(image, invert)
        rot = rotest.orientation(image) if rotest else None
        skew = skewest.skew(image) if skewest else None
        print(key, image.shape, rot, skew)


@app.command()
def show_rot(urls: List[str]):
    """Show training samples for page rotation"""
    training = make_loader(urls, shuffle=5000)
    plt.ion()
    for patches, rots in training:
        plt.imshow(patches[0].numpy())
        plt.title(repr(int(rots[0])))
        plt.show()
        plt.ginput(1, 100)
        plt.clf()


@app.command()
def show_skew(urls: List[str], abins: int = 20, sbins: int = 20):
    """Show training samples for skew"""
    training = make_loader(
        urls, pipe=partial(skew_pipe, abins=abins, sbins=sbins), shuffle=5000
    )
    plt.ion()
    for patches, abin, sbin in training:
        plt.imshow(patches[0].numpy())
        plt.title(f"{abin[0]-abins//2} {sbin[0]-sbins//2}")
        plt.show()
        plt.ginput(1, 100)
        plt.clf()


@app.command()
def noop():
    pass


if __name__ == "__main__":
    app()
