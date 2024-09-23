import subprocess
import sys
import datetime
import re

def littleEndianToBigEndian(num):
    pointer = len(num)
    newNum = ''
    while pointer > 0:
        newNum += num[pointer-2:pointer]
        pointer -= 2
    return newNum

# Check if the correct number of arguments is provided
if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} <path_to_ext4_image>")
    sys.exit(1)

ext4_image = sys.argv[1]  # File System Image

# Function to run a shell command and return the output
def run_command(command):
    return subprocess.check_output(command, shell=True, text=True)

# Listing files and directories
print("Listing files and directories:")
fls_output = run_command(f"sudo fls -r -f ext4 {ext4_image}")
print(fls_output)
print("")

# Iterate over fls output to determine orphan files
print("Orphan files:")
for line in fls_output.splitlines():
    # Check if the line contains a "*" character (indicating an orphan file)
    if "*" in line:
        print(f"Orphan File Found: {line}")

        # Extract inode number from line
        inode = line.split()[3].replace(':', '')
        print(f"Inode associated with orphan file: {inode}")

        # Run fsstat command to retrieve important filesystem information
        print("Retrieving filesystem information:")
        fsstat_output = run_command(f"sudo fsstat -f ext4 {ext4_image}")
        print(fsstat_output)
        # Extracting inode size, block size, and inode table range
        inode_size = int(re.search(r"Inode Size:\s+(\d+)", fsstat_output).group(1))
        print("Inode size: ", inode_size)
        block_size = int(re.search(r"Block Size:\s+(\d+)", fsstat_output).group(1))
        inode_table_start = int(re.search(r"Inode Table:\s+(\d+)", fsstat_output).group(1))

        # Calculate block number we want to isolate
        inodes_per_block = block_size // inode_size
        block_interest = inode_table_start + ((int(inode) - 1) // inodes_per_block)

        print(f"Block of Interest: {block_interest}")

        # Grab all the lines of journal that reference block_interest
        jls_output = run_command(f"sudo jls -f ext4 {ext4_image} | grep 'Block {block_interest}' | awk '{{print $1}}' | tr -d ':'").splitlines()
        print(jls_output)
        jls_desired_line = None

        # Determine how many inodes to skip
        skip_num = (int(inode) % inodes_per_block) - 1 if int(inode) % inodes_per_block != 0 else inodes_per_block - 1
        print("Skip Num: ", skip_num)
        for line in jls_output:
            inode_table = run_command(f"sudo jcat -f ext4 {ext4_image} {line} | dd bs={inode_size} skip={skip_num} count=1 | xxd")
            line3 = inode_table.splitlines()[2]
            bytes_extents = line3.split()[6]  # Var to see if extents > 0
            if bytes_extents != "0000":
                jls_desired_line = line

        print(f"jls desired line: {jls_desired_line}")

        # jcat to look at the hexdump of the inode table we want
        inode_table = run_command(f"sudo jcat -f ext4 {ext4_image} {jls_desired_line} | dd bs={inode_size} skip={skip_num} count=1 | xxd")
        line3 = inode_table.splitlines()[2]  # Line that tells if using extents
        bytes_40_41 = line3.split()[5]  # Magic number for extent

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"TimeStamp: {timestamp}")
        output_file = f"output_file_{ext4_image}_{timestamp}.txt"  # Output file of blkcat command return

        extentTreeDepth = line3.split()[8]
        if bytes_40_41 == "0af3" and extentTreeDepth == "0000":
            print("There is a use of extents and no extent tree")
            num_extents = line3.split()[6]

            # Store the number of extents
            first_byte = num_extents[:2]
            second_byte = num_extents[2:4]
            decimal_extents = int(f"0x{second_byte}{first_byte}", 16)
            print(f"Number of extents: {decimal_extents}")

            # Loop through the number of extents
            size_count = 56  # Place where the size of data starts
            start_addy_count = 60  # Place where data address starts

            for i in range(decimal_extents):
                print(f"Start Addy Count {start_addy_count}")
                size = run_command(f"sudo jcat -f ext4 {ext4_image} {jls_desired_line} | dd bs={inode_size} skip={skip_num} count=1 | dd bs=1 skip={size_count} count=2 | xxd")
                print("Size: ", size)
                size = size.split()[1]  # Size of the extent
                first_byte = size[:2]
                second_byte = size[2:4]
                size = int(f"0x{second_byte}{first_byte}", 16)
                print(f"Size: {size}")

                start_addy = run_command(f"sudo jcat -f ext4 {ext4_image} {jls_desired_line} | dd bs={inode_size} skip={skip_num} count=1 | dd bs=1 skip={start_addy_count} count=4 | xxd")
                start_addy = start_addy.split()[1:3]
                start_addy = ''.join(start_addy).replace(' ', '')
                first_byte = start_addy[:2]
                second_byte = start_addy[2:4]
                third_byte = start_addy[4:6]
                fourth_byte = start_addy[6:8]

                # Start address extracted from hexdump and converted from little-endian to decimal
                start_addy = int(f"0x{fourth_byte}{third_byte}{second_byte}{first_byte}", 16)
                print(f"Starting Address: {start_addy}")

                output = run_command(f"dd if={ext4_image} bs={block_size} skip={start_addy} count={size} >> outputfile.txt")

                size_count += 12
                start_addy_count += 12
        else:
            treeInfoBlockLine = inode_table.splitlines()[3]
            start_addy = run_command(f"sudo jcat -f ext4 {ext4_image} {jls_desired_line} | dd bs={inode_size} skip={skip_num} count=1 | dd bs=1 skip={56} count=6 | xxd")
            start_addy = start_addy.split()[1:3]
            start_addy = ''.join(start_addy).replace(' ', '')
            first_byte = start_addy[:2]
            second_byte = start_addy[2:4]
            third_byte = start_addy[4:6]
            fourth_byte = start_addy[6:8]

            # Start address extracted from hexdump and converted from little-endian to decimal
            start_addy = int(f"0x{fourth_byte}{third_byte}{second_byte}{first_byte}", 16)
            print(f"Starting Address: {start_addy}") 
            output = run_command(f"blkcat {ext4_image} {start_addy} | xxd")
            print(output)
            firstLine = output.splitlines()[0]
            print(firstLine)
            num_extents = firstLine.split()[2]
            first_byte = num_extents[2::]
            second_byte = num_extents[0:2]
            num_extents = int(f"0x{first_byte}{second_byte}", 16)
            skipNum = 12
            for i in range(num_extents):
                blockAddy = run_command(f"dd if={ext4_image} bs={block_size} skip={start_addy} count=1 | dd bs=1 skip={skipNum} count=12 | xxd")
                blockAddy = blockAddy.split()[1:-1]
                blockAddy = ''.join(blockAddy).replace(' ','')
                logBlockNum = blockAddy[0:8]
                numBlocks = blockAddy[8:12]
                startBlock = blockAddy[16:24]
                logBlockNum = littleEndianToBigEndian(logBlockNum)
                startBlock = littleEndianToBigEndian(startBlock)
                numBlocks = littleEndianToBigEndian(numBlocks)
                startBlock = int(startBlock,16)
                numBlocks = int(numBlocks,16)
                file = run_command(f"dd if={ext4_image} bs={block_size} skip={startBlock} count={numBlocks} >> outputfile.txt")
                skipNum += 12








# import subprocess
# import sys
# import datetime
# import re

# # Check if the correct number of arguments is provided
# if len(sys.argv) != 2:
#     print(f"Usage: {sys.argv[0]} <path_to_ext4_image>")
#     sys.exit(1)

# ext4_image = sys.argv[1]  # File System Image

# # Function to run a shell command and return the output
# def run_command(command):
#     return subprocess.check_output(command, shell=True, text=True)

# # Listing files and directories
# print("Listing files and directories:")
# fls_output = run_command(f"sudo fls -r -f ext4 {ext4_image}")
# print(fls_output)
# print("")

# # Iterate over fls output to determine orphan files
# print("Orphan files:")
# for line in fls_output.splitlines():
#     # Check if the line contains a "*" character (indicating an orphan file)
#     if "*" in line:
#         print(f"Orphan File Found: {line}")
        
#         # Extract inode number from line
#         inode = line.split()[3].replace(':', '')
#         print(f"Inode associated with orphan file: {inode}")
        
#         # Run fsstat command to retrieve important filesystem information
#         print("Retrieving filesystem information:")
#         fsstat_output = run_command(f"sudo fsstat -f ext4 {ext4_image}")
        
#         # Extracting inode size, block size, and inode table range
#         inode_size = int(re.search(r"Inode Size:\s+(\d+)", fsstat_output).group(1))
#         block_size = int(re.search(r"Block Size:\s+(\d+)", fsstat_output).group(1))
#         inode_table_start = int(re.search(r"Inode Table\s+(\d+)", fsstat_output).group(1))
        
#         # Calculate block number we want to isolate
#         inodes_per_block = block_size // inode_size
#         block_interest = inode_table_start + ((int(inode) - 1) // inodes_per_block)
        
#         print(f"Block of Interest: {block_interest}")
        
#         # Grab all the lines of journal that reference block_interest
#         jls_output = run_command(f"sudo jls -f ext4 {ext4_image} | grep 'Block {block_interest}' | awk '{{print $1}}' | tr -d ':'").splitlines()
        
#         jls_desired_line = None
        
#         # Determine how many inodes to skip
#         skip_num = (int(inode) % inodes_per_block) - 1 if int(inode) % inodes_per_block != 0 else inodes_per_block - 1
        
#         for line in jls_output:
#             inode_table = run_command(f"sudo jcat -f ext4 {ext4_image} {line} | dd bs={inode_size} skip={skip_num} count=1 | xxd")
#             line3 = inode_table.splitlines()[2]
#             bytes_extents = line3.split()[6]  # Var to see if extents > 0
#             if bytes_extents != "0000":
#                 jls_desired_line = line
#                 break
        
#         print(f"jls desired line: {jls_desired_line}")

#         # jcat to look at the hexdump of the inode table we want
#         inode_table = run_command(f"sudo jcat -f ext4 {ext4_image} {jls_desired_line} | dd bs={inode_size} skip={skip_num} count=1 | xxd")
#         line3 = inode_table.splitlines()[2]  # Line that tells if using extents
#         bytes_40_41 = line3.split()[5]  # Magic number for extent

#         timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         print(f"TimeStamp: {timestamp}")
#         output_file = f"output_file_{ext4_image}_{timestamp}.txt"  # Output file of blkcat command return
        
#         if bytes_40_41 == "0af3":
#             print("There is a use of extents")
#             num_extents = line3.split()[6]
            
#             # Store the number of extents
#             first_byte = num_extents[:2]
#             second_byte = num_extents[2:4]
#             decimal_extents = int(f"0x{second_byte}{first_byte}", 16)
#             print(f"Number of extents: {decimal_extents}")
            
#             # Loop through the number of extents
#             size_count = 56  # Place where the size of data starts
#             start_addy_count = 60  # Place where data address starts
            
#             for i in range(decimal_extents):
#                 print(f"Start Addy Count {start_addy_count}")
#                 size = run_command(f"sudo jcat -f ext4 {ext4_image} {jls_desired_line} | dd bs={inode_size} skip={skip_num} count=1 | dd bs=1 skip={size_count} count=2 | xxd")
#                 size = size.split()[1]  # Size of the extent
#                 first_byte = size[:2]
#                 second_byte = size[2:4]
#                 size = int(f"0x{second_byte}{first_byte}", 16)
#                 print(f"Size: {size}")
                
#                 start_addy = run_command(f"sudo jcat -f ext4 {ext4_image} {jls_desired_line} | dd bs={inode_size} skip={skip_num} count=1 | dd bs=1 skip={start_addy_count} count=4 | xxd")
#                 start_addy = start_addy.split()[1:3]
#                 start_addy = ''.join(start_addy).replace(' ', '')
#                 first_byte = start_addy[:2]
#                 second_byte = start_addy[2:4]
#                 third_byte = start_addy[4:6]
#                 fourth_byte = start_addy[6:8]
                
#                 # Start address extracted from hexdump and converted from little-endian to decimal
#                 start_addy = int(f"0x{fourth_byte}{third_byte}{second_byte}{first_byte}", 16)
#                 print(f"Starting Address: {start_addy}")
                
#                 output = run_command(f"dd if={ext4_image} bs={block_size} skip={start_addy} count={size} >> {output_file}")
                
#                 size_count += 12
#                 start_addy_count += 12
