#!/usr/bin/env python

from __future__ import print_function

import argparse

import PIL
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import filters, interpolation, morphology
from scipy import stats


parser = argparse.ArgumentParser(
    """
Image binarization using non-linear processing.

This is a compute-intensive binarization method that works on degraded
and historical book pages.
"""
)

parser.add_argument(
    "-n", "--nocheck", action="store_true", help="disable error checking on inputs"
)
parser.add_argument(
    "-t",
    "--threshold",
    type=float,
    default=-1,
    help="threshold, determines lightness, default: %(default)s",
)
parser.add_argument(
    "-z",
    "--zoom",
    type=float,
    default=0.5,
    help="zoom for page background estimation, smaller=faster, default: %(default)s",
)
parser.add_argument(
    "-e",
    "--escale",
    type=float,
    default=1.0,
    help="scale for estimating a mask over the text region, default: %(default)s",
)
parser.add_argument(
    "-b",
    "--bignore",
    type=float,
    default=0.1,
    help="ignore this much of the border for threshold estimation, default: %(default)s",
)
parser.add_argument(
    "-p",
    "--perc",
    type=float,
    default=80,
    help="percentage for filters, default: %(default)s",
)
parser.add_argument(
    "-r",
    "--range",
    type=int,
    default=20,
    help="range for filters, default: %(default)s",
)
parser.add_argument(
    "-m",
    "--maxskew",
    type=float,
    default=2,
    help="skew angle estimation parameters (degrees), default: %(default)s",
)
parser.add_argument(
    "-g",
    "--gray",
    action="store_true",
    help="force grayscale processing even if image seems binary",
)
parser.add_argument(
    "--lo",
    type=float,
    default=5,
    help="percentile for black estimation, default: %(default)s",
)
parser.add_argument(
    "--hi",
    type=float,
    default=90,
    help="percentile for white estimation, default: %(default)s",
)
parser.add_argument(
    "--skewsteps",
    type=int,
    default=8,
    help="steps for skew angle estimation (per degree), default: %(default)s",
)
parser.add_argument(
    "--debug",
    type=float,
    default=0,
    help="display intermediate results, default: %(default)s",
)
parser.add_argument("-o", "--output", default=None, help="output file")
parser.add_argument("fname", help="input file")

default_args = parser.parse_args(["___.jpg"])

debug_nlbin = False


def check_page(image):
    if len(image.shape) == 3:
        raise ValueError("input image is color image %s" % (image.shape,))
    if np.mean(image) < np.median(image):
        raise ValueError("image may be inverted")
    h, w = image.shape
    if h < 600:
        raise ValueError("image not tall enough for a page image %s" % (image.shape,))
    if h > 10000:
        raise ValueError("image too tall for a page image %s" % (image.shape,))
    if w < 600:
        raise ValueError("image too narrow for a page image %s" % (image.shape,))
    if w > 10000:
        raise ValueError("line too wide for a page image %s" % (image.shape,))


def estimate_skew_angle(image, angles):
    estimates = []
    for a in angles:
        v = np.mean(interpolation.rotate(image, a, order=0, mode="constant"), axis=1)
        v = np.var(v)
        estimates.append((v, a))
    if debug_nlbin > 0:
        plt.plot([y for x, y in estimates], [x for x, y in estimates])
        plt.ginput(1, debug_nlbin)
    _, a = max(estimates)
    return a


def H(s):
    return s[0].stop - s[0].start


def W(s):
    return s[1].stop - s[1].start


def A(s):
    return W(s) * H(s)


def dshow(image, info):
    if debug_nlbin <= 0:
        return
    plt.ion()
    plt.gray()
    plt.imshow(image)
    plt.title(info)
    plt.ginput(1, debug_nlbin)


def normalize_raw_image(raw):
    """ perform image normalization """
    image = raw - np.amin(raw)
    if np.amax(image) == np.amin(image):
        raise ValueError("image is empty")
    image /= np.amax(image)
    return image


def estimate_local_whitelevel(image, zoom=0.5, perc=80, range=20, debug=0):
    """flatten it by estimating the local whitelevel
    zoom for page background estimation, smaller=faster, default: %(default)s
    percentage for filters, default: %(default)s
    range for filters, default: %(default)s
    """
    m = interpolation.zoom(image, zoom)
    m = filters.percentile_filter(m, perc, size=(range, 2))
    m = filters.percentile_filter(m, perc, size=(2, range))
    m = interpolation.zoom(m, 1.0 / zoom)
    if debug > 0:
        plt.clf()
        plt.imshow(m, vmin=0, vmax=1)
        plt.ginput(1, debug)
    w, h = np.minimum(np.array(image.shape), np.array(m.shape))
    flat = np.clip(image[:w, :h] - m[:w, :h] + 1, 0, 1)
    if debug > 0:
        plt.clf()
        plt.imshow(flat, vmin=0, vmax=1)
        plt.ginput(1, debug)
    return flat


def estimate_skew(flat, bignore=0.1, maxskew=2, skewsteps=8):
    """ estimate skew angle and rotate"""
    d0, d1 = flat.shape
    o0, o1 = int(bignore * d0), int(bignore * d1)  # border ignore
    flat = np.amax(flat) - flat
    flat -= np.amin(flat)
    est = flat[o0 : d0 - o0, o1 : d1 - o1]
    ma = maxskew
    ms = int(2 * maxskew * skewsteps)
    # print(linspace(-ma,ma,ms+1))
    angle = estimate_skew_angle(est, np.linspace(-ma, ma, ms + 1))
    flat = interpolation.rotate(flat, angle, mode="constant", reshape=0)
    flat = np.amax(flat) - flat
    return flat, angle


def estimate_thresholds(flat, bignore=0.1, escale=1.0, lo=5, hi=90, debug=0):
    """# estimate low and high thresholds
    ignore this much of the border for threshold estimation, default: %(default)s
    scale for estimating a mask over the text region, default: %(default)s
    lo percentile for black estimation, default: %(default)s
    hi percentile for white estimation, default: %(default)s
    """
    d0, d1 = flat.shape
    o0, o1 = int(bignore * d0), int(bignore * d1)
    est = flat[o0 : d0 - o0, o1 : d1 - o1]
    if escale > 0:
        # by default, we use only regions that contain
        # significant variance; this makes the percentile
        # based low and high estimates more reliable
        e = escale
        v = est - filters.gaussian_filter(est, e * 20.0)
        v = filters.gaussian_filter(v ** 2, e * 20.0) ** 0.5
        v = v > 0.3 * np.amax(v)
        v = morphology.binary_dilation(v, structure=np.ones((int(e * 50), 1)))
        v = morphology.binary_dilation(v, structure=np.ones((1, int(e * 50))))
        if debug > 0:
            plt.imshow(v)
            plt.ginput(1, debug)
        est = est[v]
    lo = stats.scoreatpercentile(est.ravel(), lo)
    hi = stats.scoreatpercentile(est.ravel(), hi)
    return lo, hi


def nlbin(raw, args=default_args):
    assert raw.dtype == np.float
    image = normalize_raw_image(raw)
    flat = estimate_local_whitelevel(
        image, args.zoom, args.perc, args.range, debug_nlbin
    )
    flat, angle = estimate_skew(flat, args.bignore, args.maxskew, args.skewsteps)
    lo, hi = estimate_thresholds(
        flat, args.bignore, args.escale, args.lo, args.hi, debug_nlbin
    )
    flat -= lo
    flat /= hi - lo
    flat = np.clip(flat, 0, 1)
    return flat


def main():
    args = parser.parse_args()
    assert args.output is not None
    image = PIL.Image.open(args.fname)
    image = image.convert("L")
    image = np.asarray(image)
    assert image.dtype == np.uint8
    image = image / 255.0
    result = nlbin(image, args)
    assert result.dtype == np.float
    if args.threshold >= 0:
        result = np.array(result > args.threshold, dtype=np.uint8) * 255
    else:
        result = np.array(result * 255, dtype=np.uint8)
    result = PIL.Image.fromarray(result)
    result.save(args.output)


if __name__ == "__main__":
    main()
