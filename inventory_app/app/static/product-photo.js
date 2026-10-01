export const NO_PRODUCT_PHOTO='/static/product-no-photo-light.png';
const escapeAttribute=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function productPhoto(image, name, className='product-photo', prefix='/shop/media/', loading='lazy') {
  const src=image?prefix+encodeURIComponent(image):NO_PRODUCT_PHOTO;
  const alt=image?name:name+'：商品尚無照片';
  return `<img class="${escapeAttribute(className)}${image?'':' missing-product-photo'}" src="${src}" alt="${escapeAttribute(alt)}" loading="${escapeAttribute(loading)}" data-product-photo>`;
}

document.addEventListener('error',event=>{
  const img=event.target;
  if(!(img instanceof HTMLImageElement)||!img.hasAttribute('data-product-photo')||img.getAttribute('src')===NO_PRODUCT_PHOTO)return;
  img.src=NO_PRODUCT_PHOTO;
  img.alt='商品尚無照片';
  img.classList.add('missing-product-photo');
},true);
