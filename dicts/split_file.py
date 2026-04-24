def split_file(filename):
    with open(filename, 'rb') as file:
        content = file.read()                    # Read file content
        one_third_length = len(content) // 3     # calculate the size of one third of the file
 
        # Write the 3 parts to new files
        with open('file_part1.pcm', 'wb') as file1:
           file1.write(content[:one_third_length])

        with open('file_part2.pcm', 'wb') as file2:
            file2.write(content[one_third_length:2*one_third_length])

        with open('file_part3.pcm', 'wb') as file3:
           file3.write(content[2*one_third_length:])

# Call the function           
split_file('太阳.pcm')