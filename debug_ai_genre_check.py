from main import looks_like_ai_movie_request

samples = [
    'Jangari',
    'Komediya',
    'Jangari kino',
    'Bunday nomdagi kino topilmadi',
    'Kulgili',
    'Sokin kino',
]
for sample in samples:
    print(sample, '=>', looks_like_ai_movie_request(sample))
