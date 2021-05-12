from dataclasses import dataclass

code_length_alphabet = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]

# TODO:  bitstream class
# TODO:  parse gzip header correctly
def take(it, count):
    for _ in range(count):
        yield next(it)

def drop(it, count):
    for _ in take(it, count):  
        pass

def bitstream(buffer: bytes):
    for byte in buffer:
        for shiftval in range(8):
            yield (byte >> shiftval) & 0x1

def assemble(stream, count):
    number = 0
    for i, bit in enumerate(take(stream, count)):
        number |= (bit << i)
    return number

def running_assembly(stream, invert):
    number = 0
    for i,bit in enumerate(stream):
        if invert:
            number = (number << 1) | bit
        else:
            number |= (bit << i)
        yield number, i+1

# this code could be slimmer if dict creation happens outside of this function
# TODO: handle code length zero
def construct_huffman(alphabet, code_lengths):

    # collect characters in alphabet of the same code length into list 
    char_by_code_len = dict()
    for character, length in zip(alphabet, code_lengths):
        char_by_code_len.setdefault(length, []).append(character)  
    
    # recreate huffman codes from code lenghts
    huffman_code = dict()
    min_code = 0
    for length in sorted(char_by_code_len):
        characters = char_by_code_len[length]

        for i, character in enumerate(sorted(characters)):
            huffman_code[ (min_code + i, length) ] = character

        min_code = (min_code + len(characters)) << 1
    
    return huffman_code

def huf_decode(stream, hufman_code: dict):
    code = None
    for code in running_assembly(stream):
        if code in hufman_code:
            break
    else:
        return None
    return hufman_code[code]

@dataclass
class DeflateHeader:

    bfinal: int
    btype:  int
    hlit:   int 
    hdist:  int
    hclen:  int

# NOTE: I do not consider this nice code but this just a debugging function anyway.
def bits_to_str(stream, count: int, length = 8, sep=' '):
    bytes_val = ( take(stream, length)    for _ in range(count) ) # generator of bit generators = byte generator
    bytes_str = ( ''.join(map(str, byte)) for byte in bytes_val )
    return sep.join(bytes_str)

def print_huffmancode(huffman_tree):
    for code, character in huffman_tree.items():
        number, length = code
        binstr = bin(number)[2:].rjust(length, '0')
        print(character,'=', binstr, '=', number, length)

if __name__ == '__main__':
    gzip_header_len = 0xa

    with open('test.gz', 'rb') as fobj:
        gz = fobj.read()

    stream = bitstream(gz)

    # skip gzip header
    drop(stream, gzip_header_len * 8)
    
    # read in deflate block header
    def_header = DeflateHeader(
        assemble(stream, 1),
        assemble(stream, 2),
        assemble(stream, 5),
        assemble(stream, 5),
        assemble(stream, 4))
    
    # read in code lengths for the code alphabet
    codelengths = [assemble(stream, 3) for _ in range(4 + def_header.hclen)]

    # construct huffman tree to decode code lengths for literal/length and distance alphabets
    huf_code = construct_huffman(code_length_alphabet, codelengths)
    print_huffmancode(huf_code)
    
    # decode (huffman + run-length) encoded codelengths for (literal/length + distance) huffman code
    j = 0
    rle_codelengths = []
    while len(rle_codelengths) < (257 + def_header.hlit + def_header.hdist):
        
        # decode huffman enccoding
        rle_code = huf_decode(stream, huf_code)

        # decode run length encoding
        codes = [rle_code]
        if rle_code == 16:
            codes = [rle_codelengths[-1]] * (assemble(stream, 2) + 3)
        elif rle_code == 17:
            codes = [0] * (assemble(stream, 3) + 3)
        elif rle_code == 18:
            codes = [0] * (assemble(stream, 7) + 11)

        rle_codelengths += codes
        j += 1
    
    print(rle_codelengths)
    print(j) # == 138, agrees with value from infinite partition
