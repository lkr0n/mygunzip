#!/usr/bin/python
from dataclasses import dataclass
from argparse import ArgumentParser
import sys

rle_alphabet = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]

length_extra_bits   = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0]
distance_extra_bits = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13]

length_offset   = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258]
distance_offset = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]

fixed_huf_codelengths = 144*[8] + 112*[9] + 24*[7] + 8*[8]
fixed_litlen_alphabet = range(288)

NO_COMPRESSION = 0
FIXED          = 1
DYNAMIC        = 2
RESREVED       = 3

FTEXT          = 1
FHCRC          = 2
FEXTRA         = 4
FNAME          = 8
FCOMMENT       =16

@dataclass
class DeflateHeader:

    bfinal: int
    btype:  int
    hlit:   int
    hdist:  int
    hclen:  int

@dataclass
class GzipHeader:

    magic:        tuple
    cm:           int
    flg:          int
    mtime:        int
    xfl:          int
    os:           int
    xlen:         int     = 0
    extra_bytes:  int     = 0
    fname:        str     = None
    comment:      str     = None
    crc:          int     = 0

def take(it, count):
    for _ in range(count):
        yield next(it)

def bitstream(buffer: bytes):
    for byte in buffer:
        for shiftval in range(8):
            yield (byte >> shiftval) & 0x1

def to_number(stream, count):
    number = 0
    for i, bit in enumerate(take(stream, count)):
        number |= (bit << i)
    return number

def generate_prefixes(stream):
    number = 0
    for bit in stream:
        number = (number << 1) | bit
        yield number

def construct_huffman(alphabet, code_lengths):

    # collect characters in alphabet of the same code length into list 
    char_by_code_len = dict()
    for character, length in zip(alphabet, code_lengths):
        if length:
            characters = char_by_code_len.setdefault(length, [])
            characters.append(character)
    
    # recreate huffman codes from code lenghts
    min_code = 0
    huffman_code = dict()
    max_bitwidth = max(char_by_code_len) + 1

    for length in range(max_bitwidth):

        if length in char_by_code_len:
            characters = sorted(char_by_code_len[length])

            for i, character in enumerate(characters):
                huffman_code[ (length, min_code + i) ] = character

            min_code += len(characters)

        min_code <<= 1
    
    return huffman_code

def decode_cstring(stream):
    string = []
    while (byte := to_number(stream, 8)):
        string.append(chr(byte))
    return ''.join(string)

def decode_codelengths(stream, huf_code, count):
    codelengths = []
    while len(codelengths) < count:

        # decode huffman enccoding
        rle_code = decode_huf(stream, huf_code)

        # decode run length encoding
        codes = [rle_code]

        if rle_code == 16:
            codes = [codelengths[-1]] * (to_number(stream, 2) + 3)
        elif rle_code == 17:
            codes = [0] * (to_number(stream, 3) + 3)
        elif rle_code == 18:
            codes = [0] * (to_number(stream, 7) + 11)

        codelengths += codes
    return codelengths

def decode_huf(stream, hufman_code: dict):
    for code in enumerate(generate_prefixes(stream), start=1):
        if code in hufman_code:
            return hufman_code[code]
    return None

def inflate(stream, litlen_huf_code, dist_huf_code):
    uncompressed_data = bytearray()

    # read in from literal/len alphabet until end of block symbol
    while (symbol := decode_huf(stream, litlen_huf_code)) != 256:

        if symbol < 257:
            # output literal
            uncompressed_data.append(symbol)
            print(f"literal {hex(symbol)}")
        else:
            # parse length symbol
            length   = to_number(stream, length_extra_bits[symbol - 257])
            length  += length_offset[symbol - 257]

            # parse backwards distance symbol
            dist_symbol = decode_huf(stream, dist_huf_code)
            distance    = to_number(stream, distance_extra_bits[dist_symbol])
            distance   += distance_offset[dist_symbol]

            # inflate length, distance pair
            data_slice = uncompressed_data[-distance:]
            for i in range(length):
                uncompressed_data.append(data_slice[i % distance])

            print(f"match {length}, {distance}")

    return uncompressed_data


def deflate_header_from_stream(stream):

    bfinal = to_number(stream, 1)
    btype =  to_number(stream, 2)
    hlit = hdist = hclen = 0

    if btype == DYNAMIC:
        hlit = to_number(stream, 5)
        hdist = to_number(stream, 5)
        hclen = to_number(stream, 4)

    return DeflateHeader(bfinal, btype, hlit, hdist, hclen)

def gzip_header_from_stream(stream):

    magic   = (to_number(stream, 8), to_number(stream, 8))
    cm      = to_number(stream, 8)
    flg     = to_number(stream, 8)
    mtime   = to_number(stream, 32)
    xfl     = to_number(stream, 8)
    os      = to_number(stream, 8)

    kwargs = dict()
    if flg & FEXTRA:
        kwargs['xlen']          = to_number(stream, 16)
        kwargs['extra_bytes']   = to_number(stream, kwargs['xlen'])

    if flg & FNAME:
        kwargs['fname'] = decode_cstring(stream)

    if flg & FCOMMENT:
        kwargs['comment'] = decode_cstring(stream)

    if flg & FHCRC:
        kwargs['crc'] = to_number(stream, 8)

    return GzipHeader(magic, cm, flg, mtime, xfl, os, **kwargs)

def print_huffman_code(hufman_code):
    print("sym", "dec", "bin", "length", sep='\t')
    for code, char in hufman_code.items():
        length, code =  code
        binstr = bin(code)[2:].rjust(length, '0')
        print(char, code, binstr, length, sep='\t')

if __name__ == '__main__':

    parser = ArgumentParser(description='small gunzip implementation')
    parser.add_argument('--file', required=True, type=str, help='file to unzip' )
    args = parser.parse_args()

    with open(args.file, 'rb') as fobj:
        gz = fobj.read()

    stream     = bitstream(gz)
    gz_header  = gzip_header_from_stream(stream)
    def_header = deflate_header_from_stream(stream)

    uncompressed_data = bytes()

    if def_header.btype == DYNAMIC:

        # read in code lengths for the code alphabet
        rle_codelengths = [to_number(stream, 3) for _ in range(4 + def_header.hclen)]
        huf_code = construct_huffman(rle_alphabet, rle_codelengths)

        # decode 257 + hlit + hdist + 1 codelengths
        litlen_codelengths = decode_codelengths(stream, huf_code, def_header.hlit  + 257)
        dist_codelengths   = decode_codelengths(stream, huf_code, def_header.hdist + 1)

        # recreate huffman codes from the code lenghts
        litlen_huf_code = construct_huffman(range(def_header.hlit  + 257), litlen_codelengths)
        dist_huf_code   = construct_huffman(range(def_header.hdist + 1), dist_codelengths)

        # inflate the date using the previously constructed huffman codes
        uncompressed_data = inflate(stream, litlen_huf_code, dist_huf_code)

        print("Huffman Code for Codelengths")
        print_huffman_code(huf_code)

        print("Huffman Code for Literal/Length Symbols")
        print_huffman_code(litlen_huf_code)

        print("Huffman Code for Distance Symbols")
        print_huffman_code(dist_huf_code)

    elif def_header.btype == FIXED:

        litlen_fixed_huf_code = construct_huffman(fixed_litlen_alphabet, fixed_huf_codelengths)
        dist_huf_code = { (5, dist_code): dist_code  for dist_code in range(32) }

        uncompressed_data = inflate(stream, litlen_fixed_huf_code, dist_huf_code)

    elif def_header.btype == NO_COMPRESSION:
        sys.exit("Error: btype = 0 not implemented yet")
    else:
        sys.exit("Error: invalid block type")

    # write the uncompressed data to disk
    outfilename = args.file.removesuffix('.gz')

    if gz_header.fname:
        outfilename = gz_header.fname

    with open(outfilename, 'wb') as fobj:
        fobj.write(uncompressed_data)
