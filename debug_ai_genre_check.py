from main import looks_like_ai_movie_request

samples = [
    'Jangari',
    'Komediya',
    'Kulgili',
    'Romantika',
    'Bunday nomdagi kino topilmadi',
    
    
]
for sample in samples:
    print(sample, '=>', looks_like_ai_movie_request(sample))
