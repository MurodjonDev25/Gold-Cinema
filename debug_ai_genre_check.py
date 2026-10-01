from main import looks_like_ai_movie_request

samples = [
    'Jangari',
    'Qo\`rqinchli'
    'Komediya',
    'Kulgili',
    'Romantika',
    'Bunday nomdagi kino topilmadi',
    'Multfilm, animatsiya',
   
]
for sample in samples:
    print(sample, '=>', looks_like_ai_movie_request(sample))
